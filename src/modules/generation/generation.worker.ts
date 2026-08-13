import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { TaskStatus } from "@prisma/client";

import { AppError } from "../../common/errors/app-error";
import {
  MediaService,
  type GeneratedMediaInput,
} from "../../common/media/media.service";
import { ModelGatewayService } from "../model-gateway/model-gateway.service";
import { ProductsService } from "../products/products.service";
import { GenerationEventsService } from "./generation-events.service";
import { GenerationRepository } from "./generation.repository";
import { transitionTaskState } from "./generation-state";

@Injectable()
export class GenerationWorker {
  private readonly logger = new Logger(GenerationWorker.name);
  private running = false;

  constructor(
    private readonly config: ConfigService,
    private readonly repository: GenerationRepository,
    private readonly models: ModelGatewayService,
    private readonly products: ProductsService,
    private readonly media: MediaService,
    private readonly events: GenerationEventsService,
  ) {}

  /**
   * 目的：单进程领取并执行一个 MySQL 持久化生成任务。
   * 输入：由定时调度器触发。
   * 输出：更新任务状态和结果。
   * 外部副作用：调用供应商 API、下载结果由后续 Asset Adapter 承担。
   * 并发：同一进程最多处理一个任务。
   * 恢复：租约过期后任务可以再次被领取。
   */
  async tick() {
    if (
      this.running ||
      !this.config.get<boolean>("GENERATION_WORKER_ENABLED", true)
    )
      return;
    if (!this.config.get<string>("DATABASE_URL")) return;
    this.running = true;
    try {
      const now = new Date();
      const leaseUntil = new Date(now.getTime() + 2 * 60 * 1000);
      const claimed = await this.repository.claimNext(now, leaseUntil);
      if (!claimed?.task) return;
      await this.process(claimed.task.id, claimed.claimedFrom);
    } catch (error) {
      this.logger.error(error);
    } finally {
      this.running = false;
    }
  }

  private async process(taskId: string, claimedFrom: TaskStatus) {
    const task = await this.repository.findForWorker(taskId);
    if (!task) return;
    if (
      task.status === TaskStatus.CANCEL_REQUESTED ||
      claimedFrom === TaskStatus.CANCEL_REQUESTED
    ) {
      if (task.providerTaskId) {
        const request = this.models.toProviderRequest(task.modelProfile, {
          type: task.type,
          prompt: String(
            (task.promptSnapshot as Record<string, unknown>).promptText ?? "",
          ),
          negativePrompt: String(
            (task.promptSnapshot as Record<string, unknown>).negativePrompt ??
              "",
          ),
          idempotencyKey: task.id,
        });
        await this.models
          .cancel(request, task.providerTaskId)
          .catch(() => undefined);
      }
      await this.repository.update(task.id, {
        status: TaskStatus.CANCELLED,
        completedAt: new Date(),
        leaseUntil: null,
        nextPollAt: null,
      });
      this.events.publish(task.id, "generation.cancelled", {
        status: TaskStatus.CANCELLED,
      });
      return;
    }

    const promptSnapshot = task.promptSnapshot as Record<string, unknown>;
    try {
      const inputAssetIds = Array.isArray(task.inputAssets)
        ? task.inputAssets.map(String)
        : [];
      const inputAssets = await this.products.providerAssetUrls(
        task.productId,
        inputAssetIds,
      );
      const request = this.models.toProviderRequest(task.modelProfile, {
        type: task.type,
        prompt: String(promptSnapshot.promptText ?? ""),
        negativePrompt: String(promptSnapshot.negativePrompt ?? ""),
        inputAssets,
        options:
          typeof promptSnapshot.options === "object" &&
          promptSnapshot.options !== null
            ? (promptSnapshot.options as Record<string, unknown>)
            : undefined,
        idempotencyKey: task.id,
      });

      if (!task.providerTaskId) {
        const attempt = await this.repository.createAttempt({
          taskId: task.id,
          attempt: task.retryCount + 1,
          status: TaskStatus.RUNNING,
          request: {
            type: task.type,
            model: task.modelProfile.name,
            inputAssetCount: inputAssets.length,
          },
        });
        const submitted = await this.models.submit(request);
        await this.repository.updateAttempt(attempt.id, {
          providerTaskId: submitted.providerTaskId,
          response: this.compactProviderPayload(submitted.raw),
          status:
            submitted.status === "succeeded"
              ? TaskStatus.SUCCEEDED
              : TaskStatus.PROVIDER_SUBMITTED,
          finishedAt: submitted.status === "succeeded" ? new Date() : null,
        });
        if (submitted.status === "succeeded") {
          await this.repository.update(task.id, {
            providerTaskId: submitted.providerTaskId,
          });
          await this.succeed(task.id, submitted.output);
        } else {
          await this.repository.update(task.id, {
            status: transitionTaskState(
              task.status,
              TaskStatus.PROVIDER_SUBMITTED,
            ),
            providerTaskId: submitted.providerTaskId,
            nextPollAt: this.nextPollAt(),
            leaseUntil: null,
          });
          this.events.publish(task.id, "generation.provider_submitted", {
            status: TaskStatus.PROVIDER_SUBMITTED,
            providerTaskId: submitted.providerTaskId,
          });
        }
        return;
      }

      const polled = await this.models.poll(request, task.providerTaskId);
      if (polled.status === "processing") {
        await this.repository.update(task.id, {
          status: transitionTaskState(
            task.status,
            TaskStatus.PROVIDER_PROCESSING,
          ),
          nextPollAt: this.nextPollAt(),
          leaseUntil: null,
          heartbeatAt: new Date(),
        });
        this.events.publish(task.id, "generation.progress", {
          status: TaskStatus.PROVIDER_PROCESSING,
        });
        return;
      }
      if (polled.status === "succeeded") {
        await this.succeed(task.id, polled.output);
        return;
      }
      await this.fail(
        task.id,
        polled.errorCode ?? "MODEL_PROVIDER_FAILED",
        polled.errorSummary ?? "供应商任务失败",
        true,
      );
    } catch (error) {
      await this.fail(
        task.id,
        error instanceof Error ? error.name : "GENERATION_WORKER_ERROR",
        error instanceof Error ? error.message : "生成任务执行失败",
        false,
      );
    }
  }

  private async succeed(taskId: string, output?: Record<string, unknown>) {
    const task = await this.repository.findForWorker(taskId);
    if (!task) return;
    let assets: Array<Record<string, unknown>>;
    try {
      assets = await this.persistGeneratedAssets(task, output);
    } catch (error) {
      await this.fail(
        task.id,
        error instanceof AppError
          ? error.code
          : "GENERATION_RESULT_PERSIST_FAILED",
        error instanceof Error ? error.message : "生成结果保存失败",
        false,
      );
      return;
    }
    const updated = await this.repository.update(taskId, {
      status: transitionTaskState(task.status, TaskStatus.SUCCEEDED),
      output: {
        status: "succeeded",
        assets,
      },
      completedAt: new Date(),
      leaseUntil: null,
      nextPollAt: null,
    });
    this.events.publish(taskId, "generation.succeeded", {
      status: updated.status,
      output: updated.output ?? {},
    });
  }

  private async fail(
    taskId: string,
    errorCode: string,
    errorSummary: string,
    resetProviderTask = false,
  ) {
    const task = await this.repository.findForWorker(taskId);
    if (!task) return;
    const retryable = task.retryCount < task.maxRetries;
    const nextStatus = retryable ? TaskStatus.RETRY_WAITING : TaskStatus.FAILED;
    const updated = await this.repository.update(taskId, {
      status: nextStatus,
      retryCount: retryable ? { increment: 1 } : undefined,
      errorCode,
      errorSummary: errorSummary.slice(0, 1000),
      nextPollAt: retryable ? this.nextPollAt(3) : null,
      leaseUntil: null,
      completedAt: retryable ? null : new Date(),
      providerTaskId: resetProviderTask ? null : undefined,
      output: retryable ? null : undefined,
    });
    this.events.publish(
      taskId,
      retryable ? "generation.retry_waiting" : "generation.failed",
      {
        status: updated.status,
        errorCode,
        errorSummary: errorSummary.slice(0, 1000),
      },
    );
  }

  private async persistGeneratedAssets(
    task: Awaited<ReturnType<GenerationRepository["findForWorker"]>>,
    output?: Record<string, unknown>,
  ) {
    if (!task || !output) {
      throw new AppError(
        "MODEL_PROVIDER_EMPTY_OUTPUT",
        "供应商没有返回生成结果",
        502,
      );
    }
    const candidates = this.extractMediaCandidates(output);
    if (candidates.length === 0) {
      throw new AppError(
        "MODEL_PROVIDER_EMPTY_OUTPUT",
        "供应商没有返回可保存的图片或视频",
        502,
      );
    }
    const assets: Array<Record<string, unknown>> = [];
    const createdStorageKeys: string[] = [];
    const createdAssetIds: string[] = [];
    try {
      for (const candidate of candidates) {
        const stored = await this.media.saveGeneratedResult(
          task.productId,
          task.id,
          candidate,
        );
        createdStorageKeys.push(stored.storageKey);
        const existing = await this.repository.findAssetByTaskAndSha256(
          task.id,
          stored.sha256,
        );
        if (existing) {
          await this.media.remove(stored.storageKey);
          assets.push({
            id: existing.id,
            mimeType: existing.mimeType,
            byteSize: existing.byteSize,
          });
          continue;
        }
        const asset = await this.repository.createAsset({
          taskId: task.id,
          productId: task.productId,
          storageKey: stored.storageKey,
          originalName: stored.originalName,
          mimeType: stored.mimeType,
          byteSize: stored.byteSize,
          sha256: stored.sha256,
          sourceUrl: stored.sourceUrl,
        });
        createdAssetIds.push(asset.id);
        assets.push({
          id: asset.id,
          mimeType: asset.mimeType,
          byteSize: asset.byteSize,
        });
      }
      return assets;
    } catch (error) {
      await Promise.allSettled(
        createdStorageKeys.map((storageKey) => this.media.remove(storageKey)),
      );
      await this.repository
        .deleteAssets(createdAssetIds)
        .catch(() => undefined);
      throw error;
    }
  }

  private extractMediaCandidates(output: Record<string, unknown>) {
    const candidates: GeneratedMediaInput[] = [];
    const visit = (value: unknown, inheritedMimeType?: string, depth = 0) => {
      if (depth > 5 || value === null || value === undefined) return;
      if (typeof value === "string") {
        if (/^https?:\/\//i.test(value)) {
          candidates.push({
            sourceUrl: value,
            mimeType: inheritedMimeType,
          });
        } else if (
          value.startsWith("data:") ||
          (value.length > 128 && /^[A-Za-z0-9+/=_-]+$/.test(value))
        ) {
          candidates.push({
            base64: value,
            mimeType: inheritedMimeType,
          });
        }
        return;
      }
      if (Array.isArray(value)) {
        for (const item of value) visit(item, inheritedMimeType, depth + 1);
        return;
      }
      if (typeof value !== "object") return;
      const record = value as Record<string, unknown>;
      const mimeType =
        typeof record.mime_type === "string"
          ? record.mime_type
          : typeof record.mimeType === "string"
            ? record.mimeType
            : inheritedMimeType;
      for (const key of [
        "url",
        "image_url",
        "video_url",
        "download_url",
        "file_url",
        "source_url",
        "b64_json",
        "base64",
      ]) {
        if (record[key] !== undefined) visit(record[key], mimeType, depth + 1);
      }
      for (const key of [
        "data",
        "output",
        "result",
        "images",
        "videos",
        "files",
      ]) {
        if (record[key] !== undefined) visit(record[key], mimeType, depth + 1);
      }
    };
    visit(output);
    const unique = new Map<string, GeneratedMediaInput>();
    for (const candidate of candidates) {
      const key = candidate.sourceUrl ?? candidate.base64;
      if (key) unique.set(key, candidate);
    }
    return [...unique.values()];
  }

  private compactProviderPayload(payload?: Record<string, unknown>) {
    if (!payload) return undefined;
    return {
      status: payload.status ?? payload.state,
      id: payload.id ?? payload.task_id ?? payload.taskId,
      errorCode: payload.error_code,
      hasOutput: Boolean(payload.output ?? payload.result ?? payload.data),
    };
  }

  private nextPollAt(multiplier = 1) {
    const intervalMs = this.config.get<number>(
      "GENERATION_POLL_INTERVAL_MS",
      5000,
    );
    return new Date(Date.now() + intervalMs * multiplier);
  }
}
