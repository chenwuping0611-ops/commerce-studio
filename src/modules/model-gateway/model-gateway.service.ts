import { Injectable } from "@nestjs/common";
import {
  Prisma,
  ProviderKind,
  type GenerationType,
  type ModelProfile,
  type ModelProvider,
} from "@prisma/client";

import { PrismaService } from "../../common/database/prisma.service";
import { EncryptionService } from "../../common/security/encryption.service";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { CreateModelProfileDto } from "./dto/create-model-profile.dto";
import { CreateProviderDto } from "./dto/create-provider.dto";
import { OpenAiCompatibleAdapter } from "./adapters/openai-compatible.adapter";
import type {
  ModelProviderAdapter,
  ProviderGenerationRequest,
} from "./model-gateway.types";

@Injectable()
export class ModelGatewayService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly encryption: EncryptionService,
    private readonly rbac: RbacService,
    private readonly compatibleAdapter: OpenAiCompatibleAdapter,
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
        baseUrl: dto.baseUrl.replace(/\/+$/, ""),
        apiKeyEncrypted: encrypted,
        apiKeyHint: this.encryption.hint(dto.apiKey),
        enabled: dto.enabled ?? true,
      },
    });
    return { data: { ...row, apiKeyEncrypted: undefined } };
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
    return { data: profile };
  }

  async getProfileForTask(modelProfileId: string, type: GenerationType) {
    const profile = await this.prisma.modelProfile.findUnique({
      where: { id: modelProfileId },
      include: { provider: true },
    });
    if (!profile || !profile.enabled || !profile.provider.enabled) {
      throw new Error("MODEL_PROFILE_UNAVAILABLE");
    }
    const capability = profile.capability as Record<string, unknown>;
    if (capability[type.toLowerCase()] !== true) {
      throw new Error(`MODEL_CAPABILITY_${type}_UNSUPPORTED`);
    }
    return profile;
  }

  adapterFor(provider: ModelProvider): ModelProviderAdapter {
    if (
      provider.kind === ProviderKind.OPENAI_COMPATIBLE ||
      provider.kind === ProviderKind.NATIVE
    ) {
      return this.compatibleAdapter;
    }
    return this.compatibleAdapter;
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
}
