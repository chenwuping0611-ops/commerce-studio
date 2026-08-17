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
        body: JSON.stringify(this.requestBody(request)),
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
    const completed = this.isCompletedStatus(payload.status);
    return {
      providerTaskId,
      status: completed ? "succeeded" : "submitted",
      output: completed
        ? (payload.output ??
          payload.result ??
          (payload.url ? { url: payload.url } : undefined))
        : undefined,
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
        output:
          payload.output ??
          payload.result ??
          (payload.url ? { url: payload.url } : undefined),
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

  /**
   * ToAPIs uses OpenAI-compatible authentication and paths, but its media
   * payload names differ from the generic internal task options. Keep the
   * translation here so the rest of the generation pipeline stays provider
   * agnostic.
   */
  private requestBody(request: ProviderGenerationRequest) {
    const options = request.options ?? {};
    const baseUrl = request.provider.baseUrl.toLowerCase();
    if (baseUrl.includes("toapis.com")) {
      const body: Record<string, unknown> = {
        model: request.model.name,
        prompt: request.prompt,
        ...(request.idempotencyKey
          ? { client_business_id: request.idempotencyKey }
          : {}),
      };
      if (request.type === "IMAGE") {
        body.n = this.numberOption(options.count, 1);
        body.size =
          typeof options.aspectRatio === "string"
            ? options.aspectRatio
            : "1:1";
        body.response_format = "url";
        if (request.inputAssets?.length) {
          body.image_urls = request.inputAssets;
        }
      } else {
        body.duration = this.numberOption(options.duration, 5);
        body.aspect_ratio =
          typeof options.aspectRatio === "string"
            ? options.aspectRatio
            : "16:9";
        if (request.inputAssets?.length) {
          body.image_urls = request.inputAssets;
        }
      }
      return body;
    }

    return {
      model: request.model.name,
      prompt: request.prompt,
      negative_prompt: request.negativePrompt,
      input_assets: request.inputAssets,
      ...(request.options ?? {}),
    };
  }

  private isCompletedStatus(status: unknown) {
    return ["succeeded", "success", "completed", "done"].includes(
      String(status ?? "").toLowerCase(),
    );
  }

  private numberOption(value: unknown, fallback: number) {
    const number = typeof value === "number" ? value : Number(value);
    return Number.isInteger(number) && number > 0 ? number : fallback;
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
