import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import {
  GenerationType,
  Prisma,
  ProviderKind,
  type ModelProfile,
  type ModelProvider,
} from "@prisma/client";

import { PrismaService } from "../../common/database/prisma.service";
import { AuditService } from "../../common/audit/audit.service";
import { AppError } from "../../common/errors/app-error";
import { EncryptionService } from "../../common/security/encryption.service";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { CreateModelProfileDto } from "./dto/create-model-profile.dto";
import { CreateProviderDto } from "./dto/create-provider.dto";
import { UpdateModelProfileDto } from "./dto/update-model-profile.dto";
import { UpdateProviderDto } from "./dto/update-provider.dto";
import { OpenAiCompatibleAdapter } from "./adapters/openai-compatible.adapter";
import type {
  ModelProviderAdapter,
  ProviderGenerationRequest,
} from "./model-gateway.types";

type ModelCapability = {
  image?: boolean;
  video?: boolean;
  aspectRatios?: string[];
  imageAspectRatios?: string[];
  videoAspectRatios?: string[];
  maxCount?: number;
  durationOptions?: number[];
  referenceImage?: boolean;
};

@Injectable()
export class ModelGatewayService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly encryption: EncryptionService,
    private readonly rbac: RbacService,
    private readonly compatibleAdapter: OpenAiCompatibleAdapter,
    private readonly audit: AuditService,
    private readonly config: ConfigService,
  ) {}

  listProviders(user: AuthenticatedUser) {
    this.rbac.assertPermission(user, "model_config:read:system");
    return this.prisma.modelProvider
      .findMany({
        orderBy: { createdAt: "desc" },
        include: { profiles: true },
      })
      .then((rows) => ({
        data: rows.map((row) => ({
          ...row,
          apiKeyEncrypted: undefined,
          apiKeyHint: row.apiKeyHint,
        })),
      }));
  }

  /**
   * 目的：读取官方或 OpenAI 兼容供应商公开的模型目录。
   * 输入：供应商 ID 和可选模型类型筛选。
   * 输出：不包含密钥的远程模型 ID 列表，供管理员手动创建 Model Profile。
   * 外部副作用：一次只读的供应商 HTTP 请求。
   */
  async listRemoteModels(
    user: AuthenticatedUser,
    providerId: string,
    type = "all",
  ) {
    this.rbac.assertPermission(user, "model_config:read:system");
    const provider = await this.findProviderForAdmin(providerId);
    const query = type.trim()
      ? `?type=${encodeURIComponent(type.trim())}`
      : "";
    const payload = await this.fetchProviderJson(
      provider,
      `${this.providerRelativePath(provider, "/models")}${query}`,
    );
    const rawModels = Array.isArray(payload)
      ? payload
      : Array.isArray(payload.data)
        ? payload.data
        : Array.isArray(payload.models)
          ? payload.models
          : [];
    const data = rawModels
      .filter((item): item is Record<string, unknown> => {
        return Boolean(item && typeof item === "object");
      })
      .map((item) => ({
        id: String(item.id ?? item.name ?? ""),
        name: String(item.name ?? item.id ?? ""),
        object: typeof item.object === "string" ? item.object : undefined,
        ownedBy:
          typeof item.owned_by === "string"
            ? item.owned_by
            : typeof item.ownedBy === "string"
              ? item.ownedBy
              : undefined,
      }))
      .filter((item) => item.id);
    return { data };
  }

  /**
   * 目的：读取供应商账户余额或额度摘要。
   * 说明：ToAPIs 兼容接口为 GET /v1/balance；Base URL 中已包含 /v1 时直接拼接。
   */
  async getProviderBalance(user: AuthenticatedUser, providerId: string) {
    this.rbac.assertPermission(user, "model_config:read:system");
    const provider = await this.findProviderForAdmin(providerId);
    const path = this.isToApis(provider)
      ? this.providerRelativePath(provider, "/user/balance")
      : "/balance";
    const payload = await this.fetchProviderJson(provider, path);
    const objectPayload = Array.isArray(payload) ? {} : payload;
    return { data: objectPayload.data ?? objectPayload };
  }

  async createProvider(user: AuthenticatedUser, dto: CreateProviderDto) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const encrypted = this.encryption.encrypt(dto.apiKey);
    const row = await this.prisma.modelProvider.create({
      data: {
        name: dto.name.trim(),
        kind:
          dto.kind === "NATIVE"
            ? ProviderKind.NATIVE
            : ProviderKind.OPENAI_COMPATIBLE,
        baseUrl: this.normalizeProviderBaseUrl(dto.baseUrl),
        apiKeyEncrypted: encrypted,
        apiKeyHint: this.encryption.hint(dto.apiKey),
        enabled: dto.enabled ?? true,
      },
    });
    await this.audit.record({
      actorId: user.id,
      action: "model_provider.create",
      resource: "ModelProvider",
      resourceId: row.id,
      metadata: { name: row.name, kind: row.kind },
    });
    return { data: { ...row, apiKeyEncrypted: undefined } };
  }

  /**
   * 目的：向有生成权限的工作台用户提供可用模型档案。
   * 输入：当前用户和可选的图片/视频能力筛选。
   * 输出：不包含密钥的启用中 Model Profile 列表。
   * 业务边界：不暴露供应商密钥，也不要求普通用户拥有系统配置权限。
   * 外部副作用：无。
   */
  async listAvailableProfiles(user: AuthenticatedUser, type?: GenerationType) {
    this.rbac.assertPermission(user, "generation:create:team");
    const profiles = await this.prisma.modelProfile.findMany({
      where: {
        enabled: true,
        provider: { enabled: true },
      },
      orderBy: { createdAt: "desc" },
      include: {
        provider: {
          select: { id: true, name: true, kind: true, enabled: true },
        },
      },
    });
    const data = profiles
      .filter((profile) => {
        if (!type) return true;
        const capability = (profile.capability ?? {}) as Record<
          string,
          unknown
        >;
        return (
          capability[type === GenerationType.VIDEO ? "video" : "image"] === true
        );
      })
      .map((profile) => ({
        id: profile.id,
        name: profile.name,
        capability: {
          ...(profile.capability as Record<string, unknown>),
          ...(type
            ? {
                aspectRatios: this.aspectRatios(this.capability(profile), type),
              }
            : {}),
        },
        providerId: profile.providerId,
        provider: profile.provider,
      }));
    return { data };
  }

  async createProfile(
    user: AuthenticatedUser,
    providerId: string,
    dto: CreateModelProfileDto,
  ) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const profile = await this.prisma.modelProfile.create({
      data: {
        providerId,
        name: dto.name.trim(),
        capability: JSON.parse(
          JSON.stringify(dto.capability),
        ) as Prisma.InputJsonValue,
        endpointPath: dto.endpointPath?.trim(),
        enabled: dto.enabled ?? true,
      },
    });
    await this.audit.record({
      actorId: user.id,
      action: "model_profile.create",
      resource: "ModelProfile",
      resourceId: profile.id,
      metadata: { providerId },
    });
    return { data: profile };
  }

  async updateProvider(
    user: AuthenticatedUser,
    providerId: string,
    dto: UpdateProviderDto,
  ) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const current = await this.prisma.modelProvider.findUnique({
      where: { id: providerId },
    });
    if (!current) {
      throw new AppError("MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在", 404);
    }
    const updated = await this.prisma.modelProvider.update({
      where: { id: providerId },
      data: {
        ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
        ...(dto.baseUrl === undefined
          ? {}
          : { baseUrl: this.normalizeProviderBaseUrl(dto.baseUrl) }),
        ...(dto.apiKey === undefined
          ? {}
          : {
              apiKeyEncrypted: this.encryption.encrypt(dto.apiKey),
              apiKeyHint: this.encryption.hint(dto.apiKey),
            }),
        ...(dto.enabled === undefined ? {} : { enabled: dto.enabled }),
      },
      include: { profiles: true },
    });
    await this.audit.record({
      actorId: user.id,
      action: "model_provider.update",
      resource: "ModelProvider",
      resourceId: providerId,
      metadata: {
        nameChanged: dto.name !== undefined,
        apiKeyChanged: dto.apiKey !== undefined,
        enabled: dto.enabled,
      },
    });
    return {
      data: {
        ...updated,
        apiKeyEncrypted: undefined,
      },
    };
  }

  async updateProfile(
    user: AuthenticatedUser,
    profileId: string,
    dto: UpdateModelProfileDto,
  ) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const profile = await this.prisma.modelProfile.update({
      where: { id: profileId },
      data: {
        ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
        ...(dto.capability === undefined
          ? {}
          : {
              capability: JSON.parse(
                JSON.stringify(dto.capability),
              ) as Prisma.InputJsonValue,
            }),
        ...(dto.endpointPath === undefined
          ? {}
          : { endpointPath: dto.endpointPath.trim() }),
        ...(dto.enabled === undefined ? {} : { enabled: dto.enabled }),
      },
    });
    await this.audit.record({
      actorId: user.id,
      action: "model_profile.update",
      resource: "ModelProfile",
      resourceId: profileId,
      metadata: {},
    });
    return { data: profile };
  }

  async deleteProfile(user: AuthenticatedUser, profileId: string) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const profile = await this.prisma.modelProfile.findUnique({
      where: { id: profileId },
    });
    if (!profile)
      throw new AppError("MODEL_PROFILE_NOT_FOUND", "模型配置不存在", 404);
    await this.prisma.modelProfile.update({
      where: { id: profileId },
      data: { enabled: false },
    });
    await this.audit.record({
      actorId: user.id,
      action: "model_profile.disable",
      resource: "ModelProfile",
      resourceId: profileId,
      metadata: {},
    });
    return { data: { disabled: true } };
  }

  async getProfileForTask(modelProfileId: string, type: GenerationType) {
    const profile = await this.prisma.modelProfile.findUnique({
      where: { id: modelProfileId },
      include: { provider: true },
    });
    if (!profile || !profile.enabled || !profile.provider.enabled) {
      throw new AppError("MODEL_PROFILE_UNAVAILABLE", "模型配置不可用", 409);
    }
    const capability = profile.capability as Record<string, unknown>;
    if (capability[type.toLowerCase()] !== true) {
      throw new AppError(
        `MODEL_CAPABILITY_${type}_UNSUPPORTED`,
        `模型不支持${type === "IMAGE" ? "图片" : "视频"}生成`,
        409,
      );
    }
    return profile;
  }

  normalizeTaskOptions(
    profile: ModelProfile,
    type: GenerationType,
    inputOptions: Record<string, unknown> | undefined,
    inputAssetCount: number,
  ) {
    const capability = this.capability(profile);
    const options = { ...(inputOptions ?? {}) };
    const supportedRatios = this.aspectRatios(capability, type);
    const aspectRatio =
      typeof options.aspectRatio === "string"
        ? options.aspectRatio.trim()
        : undefined;
    if (
      supportedRatios.length > 0 &&
      (!aspectRatio || !supportedRatios.includes(aspectRatio))
    ) {
      throw new AppError(
        "MODEL_ASPECT_RATIO_UNSUPPORTED",
        "当前模型不支持所选画幅比例",
        400,
      );
    }
    if (aspectRatio) options.aspectRatio = aspectRatio;

    if (inputAssetCount > 0 && capability.referenceImage === false) {
      throw new AppError(
        "MODEL_REFERENCE_IMAGE_UNSUPPORTED",
        "当前模型不支持参考图",
        400,
      );
    }

    if (type === GenerationType.IMAGE) {
      const count = this.numberOption(options.count, 1);
      const maxCount = this.numberOption(capability.maxCount, 4);
      if (count < 1 || count > maxCount) {
        throw new AppError(
          "MODEL_IMAGE_COUNT_UNSUPPORTED",
          `当前模型最多支持生成 ${maxCount} 张图片`,
          400,
        );
      }
      options.count = count;
    } else if (capability.durationOptions?.length) {
      const duration = this.numberOption(
        options.duration,
        capability.durationOptions[0],
      );
      if (!capability.durationOptions.includes(duration)) {
        throw new AppError(
          "MODEL_DURATION_UNSUPPORTED",
          "当前模型不支持所选视频时长",
          400,
        );
      }
      options.duration = duration;
    }
    return options;
  }

  capabilityFor(profile: ModelProfile, type: GenerationType) {
    const capability = this.capability(profile);
    return {
      ...capability,
      aspectRatios: this.aspectRatios(capability, type),
    };
  }

  adapterFor(provider: ModelProvider): ModelProviderAdapter {
    if (provider.kind === ProviderKind.OPENAI_COMPATIBLE) {
      return this.compatibleAdapter;
    }
    throw new AppError(
      "MODEL_NATIVE_ADAPTER_NOT_CONFIGURED",
      "该官方原生供应商尚未配置专用适配器，请使用 OpenAI 兼容接口或先完成供应商适配",
      409,
    );
  }

  async submit(request: ProviderGenerationRequest) {
    return this.adapterFor(request.provider).submit(request);
  }

  async poll(request: ProviderGenerationRequest, providerTaskId: string) {
    return this.adapterFor(request.provider).poll(request, providerTaskId);
  }

  async cancel(request: ProviderGenerationRequest, providerTaskId: string) {
    const adapter = this.adapterFor(request.provider);
    if (adapter.cancel) await adapter.cancel(request, providerTaskId);
  }

  toProviderRequest(
    profile: ModelProfile & { provider: ModelProvider },
    input: {
      type: GenerationType;
      prompt: string;
      negativePrompt?: string;
      inputAssets?: string[];
      options?: Record<string, unknown>;
      idempotencyKey?: string;
    },
  ): ProviderGenerationRequest {
    return {
      provider: profile.provider,
      model: profile,
      type: input.type,
      prompt: input.prompt,
      negativePrompt: input.negativePrompt,
      inputAssets: input.inputAssets,
      options: input.options,
      idempotencyKey: input.idempotencyKey,
    };
  }

  private capability(profile: ModelProfile) {
    const value = profile.capability;
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return value as ModelCapability;
  }

  private aspectRatios(capability: ModelCapability, type: GenerationType) {
    const specific =
      type === GenerationType.IMAGE
        ? capability.imageAspectRatios
        : capability.videoAspectRatios;
    const ratios = specific?.length ? specific : capability.aspectRatios;
    return Array.isArray(ratios)
      ? ratios
          .filter((item): item is string => typeof item === "string")
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  }

  private numberOption(value: unknown, fallback: number) {
    const number = typeof value === "number" ? value : Number(value);
    return Number.isInteger(number) ? number : fallback;
  }

  private async findProviderForAdmin(providerId: string) {
    const provider = await this.prisma.modelProvider.findUnique({
      where: { id: providerId },
    });
    if (!provider) {
      throw new AppError("MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在", 404);
    }
    return provider;
  }

  private normalizeProviderBaseUrl(value: string) {
    return value
      .trim()
      .replace(/\/+$/, "")
      .replace(/\/(?:images|videos)\/generations$/i, "");
  }

  private isToApis(provider: Pick<ModelProvider, "baseUrl">) {
    try {
      return new URL(provider.baseUrl).hostname.toLowerCase() === "toapis.com";
    } catch {
      return provider.baseUrl.toLowerCase().includes("toapis.com");
    }
  }

  private providerRelativePath(
    provider: Pick<ModelProvider, "baseUrl">,
    path: string,
  ) {
    const base = provider.baseUrl.replace(/\/+$/, "");
    if (!this.isToApis(provider) || /\/v1$/i.test(base)) return path;
    return `/v1${path.startsWith("/") ? path : `/${path}`}`;
  }

  private async fetchProviderJson(
    provider: ModelProvider,
    path: string,
  ): Promise<Record<string, any> | any[]> {
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      this.config.get<number>("MODEL_REQUEST_TIMEOUT_MS", 30000),
    );
    try {
      const baseUrl = provider.baseUrl.replace(/\/+$/, "");
      const response = await fetch(
        `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`,
        {
          method: "GET",
          headers: {
            authorization: `Bearer ${this.encryption.decrypt(provider.apiKeyEncrypted)}`,
            accept: "application/json",
          },
          signal: controller.signal,
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message =
          payload?.error?.message ??
          payload?.error ??
          payload?.message ??
          `供应商请求失败（${response.status}）`;
        throw new AppError(
          `MODEL_PROVIDER_HTTP_${response.status}`,
          String(message),
          response.status >= 500 ? 502 : 400,
        );
      }
      return payload as Record<string, any> | any[];
    } catch (error) {
      if (error instanceof AppError) throw error;
      throw new AppError(
        "MODEL_PROVIDER_NETWORK_ERROR",
        error instanceof Error && error.name === "AbortError"
          ? "供应商请求超时"
          : "供应商网络请求失败",
        502,
      );
    } finally {
      clearTimeout(timeout);
    }
  }
}
