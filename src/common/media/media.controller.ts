import {
  Controller,
  Get,
  NotFoundException,
  Param,
  Query,
  Res,
} from "@nestjs/common";
import type { Response } from "express";

import { PrismaService } from "../database/prisma.service";
import { AppError } from "../errors/app-error";
import { MediaService } from "./media.service";

@Controller("media")
export class MediaController {
  constructor(
    private readonly prisma: PrismaService,
    private readonly media: MediaService,
  ) {}

  /**
   * 目的：向模型供应商提供短期、只读的产品参考图地址。
   * 输入：产品 ID、素材 ID、过期时间和 HMAC 签名。
   * 输出：授权后的媒体流。
   * 安全边界：不接受浏览器用户身份，必须同时通过签名、过期时间和素材归属校验。
   */
  @Get("provider/:productId/:assetId")
  async providerAsset(
    @Param("productId") productId: string,
    @Param("assetId") assetId: string,
    @Query("expires") expires: string,
    @Query("token") token: string,
    @Res() response: Response,
  ) {
    if (
      !expires ||
      !token ||
      !this.media.verifyProviderAsset(productId, assetId, expires, token)
    ) {
      throw new NotFoundException("媒体不存在");
    }

    const asset = await this.prisma.productAsset.findFirst({
      where: { id: assetId, productId },
    });
    if (!asset) throw new NotFoundException("媒体不存在");

    response.setHeader("Content-Type", asset.mimeType);
    response.setHeader("Content-Length", asset.byteSize);
    response.setHeader(
      "Content-Disposition",
      `inline; filename="${asset.originalName ?? "asset"}"`,
    );
    response.setHeader("Cache-Control", "private, max-age=600");

    try {
      const stream = this.media.createReadStream(asset.storageKey);
      stream.on("error", () => response.destroy());
      stream.pipe(response);
    } catch (error) {
      if (error instanceof AppError) throw error;
      throw new NotFoundException("媒体不存在");
    }
  }
}
