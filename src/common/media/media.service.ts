import {
  createHash,
  createHmac,
  randomUUID,
  timingSafeEqual,
} from "node:crypto";
import { lookup } from "node:dns/promises";
import { createReadStream } from "node:fs";
import { mkdir, unlink, writeFile } from "node:fs/promises";
import { isIP } from "node:net";
import { basename, extname, join, normalize, resolve } from "node:path";
import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";

import { AppError } from "../errors/app-error";

export type UploadedMedia = {
  buffer: Buffer;
  originalname: string;
  mimetype: string;
  size: number;
};

export type GeneratedMediaInput = {
  sourceUrl?: string;
  base64?: string;
  mimeType?: string;
  originalName?: string;
};

const allowedMimeTypes: Record<string, string> = {
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/webp": ".webp",
  "image/gif": ".gif",
  "image/avif": ".avif",
  "video/mp4": ".mp4",
  "video/webm": ".webm",
};

const mimeTypesByExtension: Record<string, string> = Object.fromEntries(
  Object.entries(allowedMimeTypes).map(([mimeType, extension]) => [
    extension,
    mimeType,
  ]),
);

@Injectable()
export class MediaService {
  constructor(private readonly config: ConfigService) {}

  async saveUpload(productId: string, file: UploadedMedia) {
    const maxBytes = this.config.get<number>(
      "MAX_UPLOAD_BYTES",
      50 * 1024 * 1024,
    );
    if (!allowedMimeTypes[file.mimetype]) {
      throw new AppError("MEDIA_MIME_NOT_ALLOWED", "不支持的媒体类型", 415, {
        mimeType: file.mimetype,
      });
    }
    if (file.size > maxBytes) {
      throw new AppError("MEDIA_TOO_LARGE", "媒体文件超过大小限制", 413, {
        maxBytes,
      });
    }

    const extension = allowedMimeTypes[file.mimetype];
    const safeName = basename(file.originalname).replace(
      /[^a-zA-Z0-9._-]/g,
      "_",
    );
    const storageKey = join(
      productId,
      `${randomUUID()}-${safeName || `asset${extension}`}`,
    ).replace(/\\/g, "/");
    const target = this.absolutePath(storageKey);
    await mkdir(resolve(target, ".."), { recursive: true });
    await writeFile(target, file.buffer, { flag: "wx" });

    return {
      storageKey,
      originalName: safeName || `asset${extension}`,
      mimeType: file.mimetype,
      byteSize: file.size,
      sha256: createHash("sha256").update(file.buffer).digest("hex"),
    };
  }

  /**
   * 目的：把供应商返回的图片或视频 URL/Base64 结果持久化到媒体目录。
   * 输入：产品 ID、任务 ID 和供应商结果候选。
   * 输出：可写入 GenerationAsset 的文件元数据。
   * 安全边界：只允许 HTTPS/HTTP 公网地址；限制 MIME、大小和重定向。
   * 外部副作用：下载一次远程结果并写入本地文件。
   */
  async saveGeneratedResult(
    productId: string,
    taskId: string,
    input: GeneratedMediaInput,
  ) {
    let buffer: Buffer;
    let mimeType = input.mimeType?.split(";")[0].trim().toLowerCase();
    let sourceUrl: string | undefined;
    let originalName = input.originalName;

    if (input.base64) {
      const parsed = this.decodeBase64(input.base64);
      buffer = parsed.buffer;
      mimeType = mimeType || parsed.mimeType;
    } else if (input.sourceUrl) {
      sourceUrl = await this.validateRemoteUrl(input.sourceUrl);
      const remote = await this.fetchRemote(sourceUrl);
      buffer = remote.buffer;
      mimeType =
        mimeType ||
        remote.response.headers
          .get("content-type")
          ?.split(";")[0]
          .trim()
          .toLowerCase();
      originalName = originalName || this.fileNameFromUrl(sourceUrl);
      mimeType = mimeType || this.mimeTypeFromFileName(originalName);
    } else {
      throw new AppError(
        "MEDIA_RESULT_SOURCE_MISSING",
        "供应商结果缺少媒体地址或 Base64 数据",
        502,
      );
    }

    const extension = allowedMimeTypes[mimeType ?? ""];
    if (!extension) {
      throw new AppError(
        "MEDIA_MIME_NOT_ALLOWED",
        "供应商返回了不支持的媒体类型",
        415,
        { mimeType: mimeType ?? "unknown" },
      );
    }

    const maxBytes = this.config.get<number>(
      "MAX_UPLOAD_BYTES",
      50 * 1024 * 1024,
    );
    if (buffer.byteLength > maxBytes) {
      throw new AppError("MEDIA_TOO_LARGE", "生成结果超过大小限制", 413, {
        maxBytes,
      });
    }

    const safeName = basename(originalName || `generated${extension}`).replace(
      /[^a-zA-Z0-9._-]/g,
      "_",
    );
    const storageKey = join(
      productId,
      "generated",
      taskId,
      `${randomUUID()}-${safeName || `generated${extension}`}`,
    ).replace(/\\/g, "/");
    const target = this.absolutePath(storageKey);
    await mkdir(resolve(target, ".."), { recursive: true });
    await writeFile(target, buffer, { flag: "wx" });

    return {
      storageKey,
      originalName: safeName || `generated${extension}`,
      mimeType,
      byteSize: buffer.byteLength,
      sha256: createHash("sha256").update(buffer).digest("hex"),
      sourceUrl,
    };
  }

  createReadStream(storageKey: string) {
    return createReadStream(this.absolutePath(storageKey));
  }

  publicAssetUrl(productId: string, assetId: string) {
    const baseUrl = this.config
      .get<string>("PUBLIC_BASE_URL", "http://127.0.0.1:3000")
      .replace(/\/+$/, "");
    return `${baseUrl}/api/v1/products/${encodeURIComponent(productId)}/assets/${encodeURIComponent(assetId)}/content`;
  }

  /**
   * 目的：生成供应商可以直接读取的短期产品素材地址。
   * 输入：产品和素材 ID。
   * 输出：带过期时间和签名的媒体 URL。
   * 安全边界：签名只允许服务端配置的媒体文件被读取，默认有效十分钟。
   */
  providerAssetUrl(productId: string, assetId: string) {
    const expiresAt = Math.floor(Date.now() / 1000) + 10 * 60;
    const token = this.signProviderAsset(productId, assetId, expiresAt);
    const baseUrl = this.config
      .get<string>("PUBLIC_BASE_URL", "http://127.0.0.1:3000")
      .replace(/\/+$/, "");
    return `${baseUrl}/media/provider/${encodeURIComponent(productId)}/${encodeURIComponent(assetId)}?expires=${expiresAt}&token=${encodeURIComponent(token)}`;
  }

  verifyProviderAsset(
    productId: string,
    assetId: string,
    expiresText: string,
    token: string,
  ) {
    const expiresAt = Number(expiresText);
    if (
      !Number.isSafeInteger(expiresAt) ||
      expiresAt < Math.floor(Date.now() / 1000)
    ) {
      return false;
    }
    const expected = this.signProviderAsset(productId, assetId, expiresAt);
    const providedBuffer = Buffer.from(token);
    const expectedBuffer = Buffer.from(expected);
    return (
      providedBuffer.length === expectedBuffer.length &&
      timingSafeEqual(providedBuffer, expectedBuffer)
    );
  }

  relativeAssetUrl(productId: string, assetId: string) {
    return `/api/v1/products/${encodeURIComponent(productId)}/assets/${encodeURIComponent(assetId)}/content`;
  }

  relativeGenerationAssetUrl(taskId: string, assetId: string) {
    return `/api/v1/generation-tasks/${encodeURIComponent(taskId)}/assets/${encodeURIComponent(assetId)}/content`;
  }

  async remove(storageKey: string) {
    try {
      await unlink(this.absolutePath(storageKey));
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "ENOENT") throw error;
    }
  }

  absolutePath(storageKey: string) {
    const root = resolve(
      this.config.get<string>("MEDIA_ROOT", "./storage/media"),
    );
    const normalizedKey = normalize(storageKey).replace(/^([/\\])+/, "");
    const target = resolve(join(root, normalizedKey));
    if (
      target !== root &&
      !target.startsWith(`${root}\\`) &&
      !target.startsWith(`${root}/`)
    ) {
      throw new AppError("MEDIA_PATH_INVALID", "媒体路径无效", 400);
    }
    return target;
  }

  extensionForMime(mimeType: string) {
    return allowedMimeTypes[mimeType] ?? extname(mimeType);
  }

  private decodeBase64(value: string) {
    const dataUrl = value.match(/^data:([^;,]+)?;base64,(.+)$/s);
    const mimeType = dataUrl?.[1]?.toLowerCase();
    const encoded = dataUrl?.[2] ?? value;
    const buffer = Buffer.from(encoded, "base64");
    if (!buffer.byteLength) {
      throw new AppError(
        "MEDIA_RESULT_INVALID_BASE64",
        "供应商返回了空的 Base64 媒体",
        502,
      );
    }
    return { buffer, mimeType };
  }

  private async validateRemoteUrl(value: string) {
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch {
      throw new AppError(
        "MEDIA_RESULT_URL_INVALID",
        "供应商返回了无效的媒体地址",
        502,
      );
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      throw new AppError(
        "MEDIA_RESULT_URL_INVALID",
        "只允许通过 HTTP 或 HTTPS 下载生成结果",
        502,
      );
    }
    if (parsed.username || parsed.password) {
      throw new AppError(
        "MEDIA_RESULT_URL_INVALID",
        "媒体地址不能包含用户凭据",
        502,
      );
    }
    const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    if (
      hostname === "localhost" ||
      hostname.endsWith(".localhost") ||
      hostname.endsWith(".internal") ||
      this.isPrivateAddress(hostname)
    ) {
      throw new AppError(
        "MEDIA_RESULT_URL_BLOCKED",
        "供应商结果地址指向了受保护网络",
        502,
      );
    }
    await this.assertPublicHostname(hostname);
    return parsed.toString();
  }

  private isPrivateAddress(hostname: string): boolean {
    const version = isIP(hostname);
    if (version === 4) {
      const parts = hostname.split(".").map(Number);
      return (
        parts[0] === 10 ||
        parts[0] === 127 ||
        (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
        (parts[0] === 192 && parts[1] === 168) ||
        (parts[0] === 169 && parts[1] === 254) ||
        parts[0] >= 224
      );
    }
    if (version === 6) {
      const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
      if (normalized.startsWith("::ffff:")) {
        return this.isPrivateAddress(normalized.slice("::ffff:".length));
      }
      return (
        normalized === "::" ||
        normalized === "::1" ||
        normalized.startsWith("fc") ||
        normalized.startsWith("fd") ||
        normalized.startsWith("fe8") ||
        normalized.startsWith("fe9") ||
        normalized.startsWith("fea") ||
        normalized.startsWith("feb") ||
        normalized.startsWith("ff")
      );
    }
    return false;
  }

  private async assertPublicHostname(hostname: string) {
    if (isIP(hostname)) return;
    let addresses: Array<{ address: string; family: number }>;
    try {
      addresses = await lookup(hostname, { all: true, verbatim: true });
    } catch {
      throw new AppError(
        "MEDIA_RESULT_URL_BLOCKED",
        "无法解析供应商结果地址",
        502,
      );
    }
    if (
      addresses.length === 0 ||
      addresses.some((entry) => this.isPrivateAddress(entry.address))
    ) {
      throw new AppError(
        "MEDIA_RESULT_URL_BLOCKED",
        "供应商结果地址解析到了受保护网络",
        502,
      );
    }
  }

  private async fetchRemote(sourceUrl: string) {
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      this.config.get<number>("MODEL_DOWNLOAD_TIMEOUT_MS", 120000),
    );
    try {
      let nextUrl = sourceUrl;
      for (let redirectCount = 0; redirectCount <= 3; redirectCount += 1) {
        const response = await fetch(nextUrl, {
          method: "GET",
          redirect: "manual",
          signal: controller.signal,
        });
        if (response.status >= 300 && response.status < 400) {
          const location = response.headers.get("location");
          if (!location || redirectCount === 3) {
            throw new AppError(
              "MEDIA_RESULT_DOWNLOAD_FAILED",
              "生成结果重定向次数超过限制",
              502,
            );
          }
          nextUrl = await this.validateRemoteUrl(
            new URL(location, nextUrl).toString(),
          );
          continue;
        }
        if (!response.ok || !response.body) {
          throw new AppError(
            "MEDIA_RESULT_DOWNLOAD_FAILED",
            "生成结果下载失败",
            502,
            { status: response.status },
          );
        }
        return {
          response,
          buffer: await this.readBoundedBody(response),
        };
      }
      throw new AppError(
        "MEDIA_RESULT_DOWNLOAD_FAILED",
        "生成结果下载失败",
        502,
      );
    } catch (error) {
      if (error instanceof AppError) throw error;
      throw new AppError(
        "MEDIA_RESULT_DOWNLOAD_FAILED",
        error instanceof Error && error.name === "AbortError"
          ? "生成结果下载超时"
          : "生成结果下载失败",
        502,
      );
    } finally {
      clearTimeout(timeout);
    }
  }

  private async readBoundedBody(response: Response) {
    const maxBytes = this.config.get<number>(
      "MAX_UPLOAD_BYTES",
      50 * 1024 * 1024,
    );
    const contentLength = Number(response.headers.get("content-length") ?? 0);
    if (contentLength > maxBytes) {
      throw new AppError("MEDIA_TOO_LARGE", "生成结果超过大小限制", 413, {
        maxBytes,
      });
    }

    const reader = response.body!.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        total += next.value.byteLength;
        if (total > maxBytes) {
          await reader.cancel();
          throw new AppError("MEDIA_TOO_LARGE", "生成结果超过大小限制", 413, {
            maxBytes,
          });
        }
        chunks.push(next.value);
      }
      return Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)));
    } catch (error) {
      if (error instanceof AppError) throw error;
      throw new AppError(
        "MEDIA_RESULT_DOWNLOAD_FAILED",
        "生成结果读取失败",
        502,
      );
    } finally {
      reader.releaseLock();
    }
  }

  private fileNameFromUrl(value: string) {
    try {
      return basename(new URL(value).pathname) || undefined;
    } catch {
      return undefined;
    }
  }

  private mimeTypeFromFileName(fileName?: string) {
    if (!fileName) return undefined;
    return mimeTypesByExtension[extname(fileName).toLowerCase()];
  }

  private signProviderAsset(
    productId: string,
    assetId: string,
    expiresAt: number,
  ) {
    const secret = this.config.get<string>("APP_ENCRYPTION_KEY");
    if (!secret) {
      throw new AppError(
        "SYSTEM_CONFIGURATION_MISSING",
        "APP_ENCRYPTION_KEY 未配置",
        500,
      );
    }
    const key = /^[0-9a-f]{64}$/i.test(secret)
      ? Buffer.from(secret, "hex")
      : Buffer.from(secret, "utf8");
    if (key.length !== 32) {
      throw new AppError(
        "SYSTEM_CONFIGURATION_INVALID",
        "APP_ENCRYPTION_KEY 必须是 32 字节",
        500,
      );
    }
    return createHmac("sha256", key)
      .update(`${productId}:${assetId}:${expiresAt}`)
      .digest("hex");
  }
}
