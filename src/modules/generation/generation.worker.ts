import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { TaskStatus } from "@prisma/client";

import { ModelGatewayService } from "../model-gateway/model-gateway.service";
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
    const request = this.models.toProviderRequest(task.modelProfile, {
      type: task.type,
      prompt: String(promptSnapshot.promptText ?? ""),
      negativePrompt: String(promptSnapshot.negativePrompt ?? ""),
      inputAssets: Array.isArray(task.inputAssets)
        ? task.inputAssets.map(String)
        : [],
      options: undefined,
      idempotencyKey: task.id,
    });

    try {
      if (!task.providerTaskId) {
        const attempt = await this.repository.createAttempt({
          taskId: task.id,
          attempt: task.retryCount + 1,
          status: TaskStatus.RUNNING,
          request: {
            type: task.type,
            model: task.modelProfile.name,
          },
        });
        const submitted = await this.models.submit(request);
        await this.repository.updateAttempt(attempt.id, {
          providerTaskId: submitted.providerTaskId,
          response: submitted.raw,
          status:
            submitted.status === "succeeded"
              ? TaskStatus.SUCCEEDED
              : TaskStatus.PROVIDER_SUBMITTED,
          finishedAt: submitted.status === "succeeded" ? new Date() : null,
        });
        if (submitted.status === "succeeded") {
          await this.succeed(task.id, submitted.output);
        } else {
          await this.repository.update(task.id, {
            status: transitionTaskState(
              task.status,
              TaskStatus.PROVIDER_SUBMITTED,
            ),
            providerTaskId: submitted.providerTaskId,
            nextPollAt: new Date(Date.now() + 5000),
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
          nextPollAt: new Date(Date.now() + 5000),
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
      );
    } catch (error) {
      await this.fail(
        task.id,
        error instanceof Error ? error.name : "GENERATION_WORKER_ERROR",
        error instanceof Error ? error.message : "生成任务执行失败",
      );
    }
  }

  private async succeed(taskId: string, output?: Record<string, unknown>) {
    const task = await this.repository.findForWorker(taskId);
    if (!task) return;
    const updated = await this.repository.update(taskId, {
      status: transitionTaskState(task.status, TaskStatus.SUCCEEDED),
      output: output ?? {},
      completedAt: new Date(),
      leaseUntil: null,
      nextPollAt: null,
    });
    this.events.publish(taskId, "generation.succeeded", {
      status: updated.status,
      output: output ?? {},
    });
  }

  private async fail(taskId: string, errorCode: string, errorSummary: string) {
    const task = await this.repository.findForWorker(taskId);
    if (!task) return;
    const retryable = task.retryCount < task.maxRetries;
    const nextStatus = retryable ? TaskStatus.RETRY_WAITING : TaskStatus.FAILED;
    const updated = await this.repository.update(taskId, {
      status: nextStatus,
      retryCount: retryable ? { increment: 1 } : undefined,
      errorCode,
      errorSummary: errorSummary.slice(0, 1000),
      nextPollAt: retryable ? new Date(Date.now() + 15000) : null,
      leaseUntil: null,
      completedAt: retryable ? null : new Date(),
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
}
