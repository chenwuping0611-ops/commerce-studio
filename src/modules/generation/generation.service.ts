import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { TaskStatus } from "@prisma/client";

import { AppError } from "../../common/errors/app-error";
import { MediaService } from "../../common/media/media.service";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { ProductMemoryService } from "../product-memory/product-memory.service";
import { PromptEngineService } from "../prompts/prompt-engine.service";
import { ProductsService } from "../products/products.service";
import { ModelGatewayService } from "../model-gateway/model-gateway.service";
import { CreateGenerationTaskDto } from "./dto/create-generation-task.dto";
import { GenerationEventsService } from "./generation-events.service";
import { GenerationRepository } from "./generation.repository";
import { transitionTaskState } from "./generation-state";

@Injectable()
export class GenerationService {
  constructor(
    private readonly repository: GenerationRepository,
    private readonly products: ProductsService,
    private readonly memory: ProductMemoryService,
    private readonly prompts: PromptEngineService,
    private readonly models: ModelGatewayService,
    private readonly rbac: RbacService,
    private readonly events: GenerationEventsService,
    private readonly media: MediaService,
    private readonly config: ConfigService,
  ) {}

  /**
   * 目的：创建一个带 Product Memory 和 Prompt 快照的异步生成任务。
   * 输入：当前用户、产品、创意、模型档案和幂等键。
   * 输出：持久化后的 GenerationTask。
   * 外部副作用：只写 MySQL；模型调用由 Worker 异步执行。
   * 幂等性：相同用户和 Idempotency-Key 返回原任务。
   * 事务：任务写入前完成产品、记忆和模型能力校验。
   */
  async create(
    user: AuthenticatedUser,
    dto: CreateGenerationTaskDto,
    headerIdempotencyKey?: string,
  ) {
    this.rbac.assertPermission(user, "generation:create:team");
    const idempotencyKey =
      dto.idempotencyKey?.trim() || headerIdempotencyKey?.trim();
    if (idempotencyKey) {
      const existing = await this.repository.findByIdempotencyKey(
        user.id,
        idempotencyKey,
      );
      if (existing) {
        return {
          data: this.toPublicTask(existing),
          meta: { idempotent: true },
        };
      }
    }

    const product = await this.products.getById(user, dto.productId);
    if (
      dto.variantId &&
      !product.data.variants.some((variant) => variant.id === dto.variantId)
    ) {
      throw new AppError(
        "PRODUCT_VARIANT_NOT_FOUND",
        "生成任务的 SKU 不属于当前产品",
        400,
      );
    }
    const inputAssets = await this.products.validateAssetReferences(
      user,
      dto.productId,
      dto.inputAssets ?? [],
    );
    const memorySnapshot = await this.memory.latestSnapshot(
      user,
      dto.productId,
    );
    const prompt = await this.prompts.compile(user, dto.productId, {
      idea: dto.idea,
      type: dto.type,
      aspectRatio:
        typeof dto.options?.aspectRatio === "string"
          ? dto.options.aspectRatio
          : undefined,
    });
    const profile = await this.models.getProfileForTask(
      dto.modelProfileId,
      dto.type,
    );

    const task = await this.repository.create({
      productId: product.data.id,
      variantId: dto.variantId,
      createdById: user.id,
      providerId: profile.providerId,
      modelProfileId: profile.id,
      type: dto.type,
      status: transitionTaskState(TaskStatus.CREATED, TaskStatus.QUEUED),
      idea: dto.idea.trim(),
      promptSnapshot: {
        ...prompt.data,
        options: dto.options ?? {},
      },
      memorySnapshot,
      inputAssets,
      idempotencyKey,
      maxRetries: this.config.get<number>("GENERATION_MAX_RETRIES", 2),
      nextPollAt: new Date(),
    });
    this.events.publish(task.id, "generation.queued", {
      status: task.status,
      createdAt: task.createdAt.toISOString(),
    });
    return { data: this.toPublicTask(task), meta: { idempotent: false } };
  }

  async list(user: AuthenticatedUser, take = 20, cursor?: string) {
    const boundedTake = Math.min(Math.max(take, 1), 100);
    const where = this.rbac.isSystemAdmin(user)
      ? {}
      : {
          OR: [
            { createdById: user.id },
            { product: { teamId: { in: user.teamIds } } },
          ],
        };
    const rows = await this.repository.list(where, boundedTake, cursor);
    const hasNext = rows.length > boundedTake;
    const data = hasNext ? rows.slice(0, boundedTake) : rows;
    return {
      data: data.map((task) => this.toPublicTask(task)),
      meta: {
        nextCursor: hasNext ? (data[data.length - 1]?.id ?? null) : null,
      },
    };
  }

  async get(user: AuthenticatedUser, id: string) {
    const task = await this.repository.findById(id);
    this.assertReadable(user, task);
    return { data: this.toPublicTask(task) };
  }

  async cancel(user: AuthenticatedUser, id: string) {
    const task = await this.repository.findById(id);
    this.assertReadable(user, task);
    if (task.createdById !== user.id && !this.rbac.isSystemAdmin(user)) {
      throw new AppError(
        "RBAC_GENERATION_CANCEL_DENIED",
        "只能取消自己的任务",
        403,
      );
    }
    const cancellableStatuses: TaskStatus[] = [
      TaskStatus.QUEUED,
      TaskStatus.RUNNING,
      TaskStatus.PROVIDER_SUBMITTED,
      TaskStatus.PROVIDER_PROCESSING,
    ];
    if (!cancellableStatuses.includes(task.status)) {
      throw new AppError(
        "GENERATION_CANCEL_NOT_ALLOWED",
        "当前任务状态不能取消",
        409,
      );
    }
    const updated = await this.repository.update(id, {
      status: transitionTaskState(task.status, TaskStatus.CANCEL_REQUESTED),
    });
    this.events.publish(id, "generation.cancel_requested", {
      status: updated.status,
    });
    return { data: this.toPublicTask(updated) };
  }

  async retry(user: AuthenticatedUser, id: string) {
    const task = await this.repository.findById(id);
    this.assertReadable(user, task);
    const retryableStatuses: TaskStatus[] = [
      TaskStatus.FAILED,
      TaskStatus.EXPIRED,
    ];
    if (!retryableStatuses.includes(task.status)) {
      throw new AppError(
        "GENERATION_RETRY_NOT_ALLOWED",
        "当前任务不能重试",
        409,
      );
    }
    if (task.retryCount >= task.maxRetries) {
      throw new AppError(
        "GENERATION_RETRY_LIMIT",
        "任务已达到最大重试次数",
        409,
      );
    }
    const updated = await this.repository.update(id, {
      status: transitionTaskState(task.status, TaskStatus.RETRY_WAITING),
      retryCount: { increment: 1 },
      nextPollAt: new Date(),
      errorCode: null,
      errorSummary: null,
      providerTaskId: null,
      output: null,
      completedAt: null,
      leaseUntil: null,
      heartbeatAt: null,
    });
    this.events.publish(id, "generation.retry_waiting", {
      status: updated.status,
    });
    return { data: this.toPublicTask(updated) };
  }

  async getAssetForRead(
    user: AuthenticatedUser,
    taskId: string,
    assetId: string,
  ) {
    const task = await this.repository.findById(taskId);
    this.assertReadable(user, task);
    const asset = task.assets.find((item) => item.id === assetId);
    if (!asset) {
      throw new AppError("GENERATION_ASSET_NOT_FOUND", "生成结果不存在", 404);
    }
    return asset;
  }

  mediaStream(storageKey: string) {
    return this.media.createReadStream(storageKey);
  }

  assertReadable<
    T extends {
      createdById: string;
      product: { teamId: string | null };
    },
  >(user: AuthenticatedUser, task: T | null): asserts task is T {
    if (!task)
      throw new AppError("GENERATION_TASK_NOT_FOUND", "生成任务不存在", 404);
    const readable =
      this.rbac.isSystemAdmin(user) ||
      task.createdById === user.id ||
      (task.product.teamId
        ? user.teamIds.includes(task.product.teamId)
        : false);
    if (!readable)
      throw new AppError(
        "RBAC_GENERATION_SCOPE_DENIED",
        "无权访问该生成任务",
        403,
      );
  }

  private toPublicTask(task: any) {
    if (!task) return task;
    const provider = task.provider
      ? {
          id: task.provider.id,
          name: task.provider.name,
          kind: task.provider.kind,
          baseUrl: task.provider.baseUrl,
          apiKeyHint: task.provider.apiKeyHint,
          enabled: task.provider.enabled,
        }
      : task.provider;
    const assets = Array.isArray(task.assets)
      ? task.assets.map((asset: any) => ({
          id: asset.id,
          taskId: asset.taskId,
          productId: asset.productId,
          originalName: asset.originalName,
          mimeType: asset.mimeType,
          byteSize: asset.byteSize,
          sha256: asset.sha256,
          createdAt: asset.createdAt,
          url: this.media.relativeGenerationAssetUrl(task.id, asset.id),
        }))
      : task.assets;
    return {
      ...task,
      provider,
      assets,
      promptSnapshot: task.promptSnapshot,
      memorySnapshot: task.memorySnapshot,
    };
  }
}
