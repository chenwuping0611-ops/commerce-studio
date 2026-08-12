import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";

import { AppError } from "../errors/app-error";

@Injectable()
export class EncryptionService {
  constructor(private readonly config: ConfigService) {}

  encrypt(value: string) {
    const key = this.key();
    const iv = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", key, iv);
    const ciphertext = Buffer.concat([
      cipher.update(value, "utf8"),
      cipher.final(),
    ]);
    const tag = cipher.getAuthTag();
    return [
      iv.toString("base64url"),
      tag.toString("base64url"),
      ciphertext.toString("base64url"),
    ].join(".");
  }

  decrypt(value: string) {
    const [ivPart, tagPart, ciphertextPart] = value.split(".");
    if (!ivPart || !tagPart || !ciphertextPart) {
      throw new AppError("SYSTEM_ENCRYPTION_INVALID", "加密配置格式无效", 500);
    }
    try {
      const decipher = createDecipheriv(
        "aes-256-gcm",
        this.key(),
        Buffer.from(ivPart, "base64url"),
      );
      decipher.setAuthTag(Buffer.from(tagPart, "base64url"));
      return Buffer.concat([
        decipher.update(Buffer.from(ciphertextPart, "base64url")),
        decipher.final(),
      ]).toString("utf8");
    } catch {
      throw new AppError("SYSTEM_ENCRYPTION_FAILED", "无法解密供应商配置", 500);
    }
  }

  hint(value: string) {
    if (value.length <= 8) return "********";
    return `${value.slice(0, 4)}...${value.slice(-4)}`;
  }

  private key() {
    const raw = this.config.get<string>("APP_ENCRYPTION_KEY");
    if (!raw)
      throw new AppError(
        "SYSTEM_CONFIGURATION_MISSING",
        "APP_ENCRYPTION_KEY 未配置",
        500,
      );
    const key = /^[0-9a-f]{64}$/i.test(raw)
      ? Buffer.from(raw, "hex")
      : Buffer.from(raw, "utf8");
    if (key.length !== 32) {
      throw new AppError(
        "SYSTEM_CONFIGURATION_INVALID",
        "APP_ENCRYPTION_KEY 必须是 32 字节",
        500,
      );
    }
    return key;
  }
}
