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
        body: JSON.stringify(await this.requestBody(request)),
      },
      this.config.get<number>("MODEL_REQUEST_TIMEOUT_MS", 30000),
    );
    const payload = await this.parseJson(response);
    if (!response.ok) {
      throw new AppError(
        this.providerErrorCode(payload, response.status),
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

    const completed =
      this.isCompletedStatus(payload.status) || this.hasOutput(payload);
    return {
      providerTaskId,
      status: completed ? "succeeded" : "submitted",
      output: completed ? this.providerOutput(payload) : undefined,
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
      if (this.isTransientPollStatus(response.status)) {
        return {
          status: "processing",
          retryAfterMs: this.retryAfterMs(response.headers),
          raw: payload,
        };
      }
      return {
        status: "failed",
        errorCode: this.providerErrorCode(payload, response.status),
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
        errorCode: this.providerErrorCode(payload, 502),
        errorSummary: this.providerError(payload, 502),
        raw: payload,
      };
    }
    if (
      ["succeeded", "success", "completed", "done"].includes(status) ||
      this.hasOutput(payload)
    ) {
      return {
        status: "succeeded",
        output: this.providerOutput(payload),
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
    let path =
      endpointPath?.trim() ||
      (type === "VIDEO" ? "/videos/generations" : "/images/generations");
    if (
      this.isToApis(base) &&
      !/\/v1$/i.test(base) &&
      !/^\/v1(?:\/|$)/i.test(path)
    ) {
      path = `/v1${path.startsWith("/") ? path : `/${path}`}`;
    }
    return `${base}${path.startsWith("/") ? path : `/${path}`}${taskId ? `/${encodeURIComponent(taskId)}` : ""}`;
  }

  private async requestBody(request: ProviderGenerationRequest) {
    const options = request.options ?? {};
    if (this.isToApis(request.provider.baseUrl)) {
      const body: Record<string, unknown> = {
        model: request.model.name,
        prompt: request.prompt,
        ...(request.idempotencyKey
          ? { client_business_id: request.idempotencyKey }
          : {}),
      };

      if (request.type === "IMAGE") {
        body.n = this.numberOption(options.count, 1);
        body.size = this.stringOption(options.aspectRatio, "1:1");
        body.resolution = this.stringOption(options.resolution, "1k");
        body.response_format = this.stringOption(options.responseFormat, "url");
        if (request.inputAssets?.length) {
          body.reference_images = await this.toApisReferenceImages(request);
        }
      } else {
        body.duration = this.numberOption(options.duration, 5);
        body.aspect_ratio = this.stringOption(options.aspectRatio, "16:9");
        if (this.hasString(options.resolution)) {
          body.resolution = options.resolution;
        }
        if (typeof options.generateAudio === "boolean") {
          body.generate_audio = options.generateAudio;
        }
        if (typeof options.returnLastFrame === "boolean") {
          body.return_last_frame = options.returnLastFrame;
        }
        if (request.inputAssets?.length) {
          const referenceImages = await this.toApisReferenceImages(request);
          body.image_with_roles = referenceImages.map((url) => ({
            url,
            role: "reference_image",
          }));
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

  private async toApisReferenceImages(request: ProviderGenerationRequest) {
    const inputAssets = request.inputAssets ?? [];
    const apiKey = this.encryption.decrypt(request.provider.apiKeyEncrypted);
    const referenceImages: string[] = [];

    for (const [index, assetUrl] of inputAssets.entries()) {
      if (!this.requiresToApisUpload(assetUrl)) {
        referenceImages.push(assetUrl);
        continue;
      }
      referenceImages.push(
        await this.uploadToApisImage(request, apiKey, assetUrl, index),
      );
    }

    return referenceImages;
  }

  private async uploadToApisImage(
    request: ProviderGenerationRequest,
    apiKey: string,
    assetUrl: string,
    index: number,
  ) {
    const sourceResponse = await this.fetchWithTimeout(
      assetUrl,
      {
        method: "GET",
        headers: { accept: "image/*" },
      },
      this.config.get<number>("MODEL_DOWNLOAD_TIMEOUT_MS", 120000),
    );
    if (!sourceResponse.ok) {
      throw new AppError(
        "MODEL_PROVIDER_REFERENCE_DOWNLOAD_FAILED",
        `无法读取第 ${index + 1} 张参考图（HTTP ${sourceResponse.status}）`,
        502,
      );
    }

    const contentType =
      sourceResponse.headers
        .get("content-type")
        ?.split(";")[0]
        .trim()
        .toLowerCase() ?? "";
    const extension = this.toApisImageExtension(contentType);
    if (!extension) {
      throw new AppError(
        "MODEL_PROVIDER_REFERENCE_IMAGE_UNSUPPORTED",
        "ToAPIs 参考图只支持 JPEG、PNG、WebP 或 GIF",
        415,
        { contentType: contentType || "unknown" },
      );
    }

    const buffer = Buffer.from(await sourceResponse.arrayBuffer());
    if (buffer.byteLength > 10 * 1024 * 1024) {
      throw new AppError(
        "MODEL_PROVIDER_REFERENCE_IMAGE_TOO_LARGE",
        "ToAPIs 参考图不能超过 10MB",
        413,
      );
    }

    const form = new FormData();
    form.append(
      "file",
      new Blob([buffer], { type: contentType }),
      `reference-${index + 1}${extension}`,
    );
    const uploadResponse = await this.fetchWithTimeout(
      this.endpoint(request.provider.baseUrl, "/uploads/images", request.type),
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${apiKey}`,
        },
        body: form,
      },
      this.config.get<number>("MODEL_REQUEST_TIMEOUT_MS", 30000),
    );
    const payload = await this.parseJson(uploadResponse);
    if (!uploadResponse.ok || payload.success === false) {
      throw new AppError(
        this.providerErrorCode(payload, uploadResponse.status),
        this.providerError(payload, uploadResponse.status),
        uploadResponse.status >= 500 ? 502 : 400,
      );
    }

    const url =
      payload.data &&
      typeof payload.data === "object" &&
      typeof payload.data.url === "string"
        ? payload.data.url
        : typeof payload.url === "string"
          ? payload.url
          : "";
    if (!url) {
      throw new AppError(
        "MODEL_PROVIDER_INVALID_UPLOAD_RESPONSE",
        "ToAPIs 图片上传没有返回公开 URL",
        502,
      );
    }
    return url;
  }

  private toApisImageExtension(contentType: string) {
    return {
      "image/jpeg": ".jpg",
      "image/png": ".png",
      "image/webp": ".webp",
      "image/gif": ".gif",
    }[contentType];
  }

  private requiresToApisUpload(value: string) {
    try {
      const hostname = new URL(value).hostname.toLowerCase();
      if (
        hostname === "localhost" ||
        hostname === "::1" ||
        hostname === "127.0.0.1" ||
        hostname.endsWith(".local")
      ) {
        return true;
      }
      const octets = hostname.split(".").map(Number);
      if (
        octets.length === 4 &&
        octets.every(
          (octet) => Number.isInteger(octet) && octet >= 0 && octet <= 255,
        )
      ) {
        return (
          octets[0] === 10 ||
          octets[0] === 127 ||
          (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
          (octets[0] === 192 && octets[1] === 168) ||
          (octets[0] === 169 && octets[1] === 254)
        );
      }
      return false;
    } catch {
      return true;
    }
  }

  private isToApis(value: string) {
    try {
      return new URL(value).hostname.toLowerCase() === "toapis.com";
    } catch {
      return value.toLowerCase().includes("toapis.com");
    }
  }

  private isCompletedStatus(status: unknown) {
    return ["succeeded", "success", "completed", "done"].includes(
      String(status ?? "").toLowerCase(),
    );
  }

  private hasOutput(payload: Record<string, any>) {
    return Boolean(
      payload.output ??
        payload.result ??
        payload.url ??
        (Array.isArray(payload.data) && payload.data.length > 0),
    );
  }

  private providerOutput(payload: Record<string, any>) {
    if (payload.output && typeof payload.output === "object") {
      return payload.output as Record<string, unknown>;
    }
    if (payload.result && typeof payload.result === "object") {
      return payload.result as Record<string, unknown>;
    }
    if (Array.isArray(payload.data)) {
      return { data: payload.data };
    }
    if (payload.url) {
      return { url: payload.url };
    }
    return undefined;
  }

  private isTransientPollStatus(status: number) {
    return status === 408 || status === 425 || status === 429 || status >= 500;
  }

  private retryAfterMs(headers: Headers) {
    const value = headers.get("retry-after");
    if (!value) return 10000;
    const seconds = Number(value);
    if (Number.isFinite(seconds) && seconds > 0) {
      return Math.min(Math.ceil(seconds * 1000), 120000);
    }
    const date = Date.parse(value);
    if (Number.isFinite(date)) {
      return Math.min(Math.max(date - Date.now(), 1000), 120000);
    }
    return 10000;
  }

  private numberOption(value: unknown, fallback: number) {
    const number = typeof value === "number" ? value : Number(value);
    return Number.isInteger(number) && number > 0 ? number : fallback;
  }

  private hasString(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0;
  }

  private stringOption(value: unknown, fallback: string) {
    return this.hasString(value) ? value.trim() : fallback;
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

  private providerErrorCode(payload: Record<string, any>, status: number) {
    const error = payload.error;
    if (error && typeof error === "object" && error.code) {
      return String(error.code);
    }
    return String(
      payload.error_code ?? payload.code ?? `MODEL_PROVIDER_HTTP_${status}`,
    );
  }

  private providerError(payload: Record<string, any>, status: number) {
    const error = payload.error;
    const message = error && typeof error === "object" ? error.message : error;
    return String(message ?? payload.message ?? `供应商请求失败（${status}）`);
  }
}
