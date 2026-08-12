import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import type { GenerationType } from "@prisma/client";

import { AppError } from "../../../common/errors/app-error";
import { EncryptionService } from "../../../common/security/encryption.service";
import type {
  ModelProviderAdapter,
  ProviderGenerationRequest,
  ProviderPollResult,
  ProviderSubmission,
} from "../model-gateway.types";

@Injectable()
export class OpenAiCompatibleAdapter implements ModelProviderAdapter {
  constructor(
    private readonly encryption: EncryptionService,
    private readonly config: ConfigService,
  ) {}

  /**
   * 目的：通过官方或 OpenAI 兼容 Base URL 提交图片/视频生成任务。
   * 输入：供应商、模型、已编译 Prompt 和可选素材。
   * 输出：供应商任务 ID。
   * 外部副作用：一次服务端 HTTP 请求；API Key 只在服务端解密。
   * 重试：由 Generation Worker 控制，本 Adapter 不自行重试非幂等提交。
   */
  async submit(
    request: ProviderGenerationRequest,
  ): Promise<ProviderSubmission> {
    const endpoint = this.endpoint(
      request.provider.baseUrl,
      request.model.endpointPath,
      request.type,
    );
    const response = await this.fetchWithTimeout(
      endpoint,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${this.encryption.decrypt(request.provider.apiKeyEncrypted)}`,
          "content-type": "application/json",
          ...(request.idempotencyKey
            ? { "idempotency-key": request.idempotencyKey }
            : {}),
        },
        body: JSON.stringify({
          model: request.model.name,
          prompt: request.prompt,
          negative_prompt: request.negativePrompt,
          input_assets: request.inputAssets,
          ...(request.options ?? {}),
        }),
      },
      this.config.get<number>("MODEL_REQUEST_TIMEOUT_MS", 30000),
    );
    const payload = await this.parseJson(response);
    if (!response.ok) {
      throw new AppError(
        `MODEL_PROVIDER_HTTP_${response.status}`,
        this.providerError(payload, response.status),
        response.status >= 500 ? 502 : 400,
      );
    }
    const providerTaskId = String(
      payload.id ?? payload.task_id ?? payload.taskId ?? "",
    );
    if (!providerTaskId) {
      throw new AppError(
        "MODEL_PROVIDER_INVALID_RESPONSE",
        "供应商未返回任务 ID",
        502,
      );
    }
    return {
      providerTaskId,
      status: payload.status === "succeeded" ? "succeeded" : "submitted",
      output: payload.output,
      raw: payload,
    };
  }

  async poll(
    request: ProviderGenerationRequest,
    providerTaskId: string,
  ): Promise<ProviderPollResult> {
    const endpoint = this.endpoint(
      request.provider.baseUrl,
      request.model.endpointPath,
      request.type,
      providerTaskId,
    );
    const response = await this.fetchWithTimeout(
      endpoint,
      {
        method: "GET",
        headers: {
          authorization: `Bearer ${this.encryption.decrypt(request.provider.apiKeyEncrypted)}`,
          accept: "application/json",
        },
      },
      this.config.get<number>("MODEL_REQUEST_TIMEOUT_MS", 30000),
    );
    const payload = await this.parseJson(response);
    if (!response.ok) {
      return {
        status: "failed",
        errorCode: `MODEL_PROVIDER_HTTP_${response.status}`,
        errorSummary: this.providerError(payload, response.status),
        raw: payload,
      };
    }
    const status = String(
      payload.status ?? payload.state ?? "processing",
    ).toLowerCase();
    if (["failed", "error", "cancelled", "canceled"].includes(status)) {
      return {
        status: "failed",
        errorCode: String(payload.error_code ?? "MODEL_PROVIDER_FAILED"),
        errorSummary: String(
          payload.error ?? payload.message ?? "供应商任务失败",
        ),
        raw: payload,
      };
    }
    if (["succeeded", "success", "completed", "done"].includes(status)) {
      return {
        status: "succeeded",
        output: payload.output ?? payload.result,
        raw: payload,
      };
    }
    return { status: "processing", raw: payload };
  }

  async cancel(request: ProviderGenerationRequest, providerTaskId: string) {
    const endpoint = this.endpoint(
      request.provider.baseUrl,
      request.model.endpointPath,
      request.type,
      providerTaskId,
    );
    await this.fetchWithTimeout(
      endpoint,
      {
        method: "DELETE",
        headers: {
          authorization: `Bearer ${this.encryption.decrypt(request.provider.apiKeyEncrypted)}`,
        },
      },
      this.config.get<number>("MODEL_REQUEST_TIMEOUT_MS", 30000),
    );
  }

  private endpoint(
    baseUrl: string,
    endpointPath: string | null,
    type: GenerationType,
    taskId?: string,
  ) {
    const base = baseUrl.replace(/\/+$/, "");
    const path =
      endpointPath?.trim() ||
      (type === "VIDEO" ? "/videos/generations" : "/images/generations");
    return `${base}${path.startsWith("/") ? path : `/${path}`}${taskId ? `/${encodeURIComponent(taskId)}` : ""}`;
  }

  private async fetchWithTimeout(
    url: string,
    init: RequestInit,
    timeoutMs: number,
  ) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } catch (error) {
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

  private async parseJson(response: Response): Promise<Record<string, any>> {
    try {
      return (await response.json()) as Record<string, any>;
    } catch {
      throw new AppError(
        "MODEL_PROVIDER_INVALID_RESPONSE",
        "供应商返回了无法解析的响应",
        502,
      );
    }
  }

  private providerError(payload: Record<string, any>, status: number) {
    return String(
      payload.error?.message ??
        payload.error ??
        payload.message ??
        `供应商请求失败（${status}）`,
    );
  }
}
