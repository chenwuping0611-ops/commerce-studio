import {
  Body,
  BadRequestException,
  Controller,
  Delete,
  Get,
  Header,
  Param,
  Post,
  Query,
  Patch,
  Res,
  UploadedFile,
  UseInterceptors,
  UseGuards,
} from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";
import { FileInterceptor } from "@nestjs/platform-express";
import type { Response } from "express";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { CreateProductDto } from "./dto/create-product.dto";
import { CreateProductAssetDto } from "./dto/create-product-asset.dto";
import { CreateVariantDto } from "./dto/create-variant.dto";
import { UpdateProductAssetDto } from "./dto/update-product-asset.dto";
import { UpdateProductDto } from "./dto/update-product.dto";
import { ProductsService } from "./products.service";

@ApiTags("products")
@Controller("products")
@UseGuards(AuthGuard, RbacGuard)
export class ProductsController {
  constructor(private readonly service: ProductsService) {}

  @Get()
  @RequirePermission("product:read:team")
  list(
    @CurrentUser() user: AuthenticatedUser,
    @Query("take") takeText?: string,
    @Query("cursor") cursor?: string,
  ) {
    return this.service.list(user, this.parseTake(takeText), cursor);
  }

  @Get(":id")
  @RequirePermission("product:read:team")
  getById(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.getById(user, id);
  }

  @Post()
  @RequirePermission("product:update:team")
  create(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CreateProductDto,
  ) {
    return this.service.create(user, dto);
  }

  @Patch(":id")
  @RequirePermission("product:update:team")
  update(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateProductDto,
  ) {
    return this.service.update(user, id, dto);
  }

  @Post(":id/variants")
  @RequirePermission("product:update:team")
  createVariant(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") productId: string,
    @Body() dto: CreateVariantDto,
  ) {
    return this.service.createVariant(user, productId, dto);
  }

  @Get(":id/assets")
  @RequirePermission("product:read:team")
  listAssets(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.listAssets(user, id);
  }

  @Post(":id/assets")
  @RequirePermission("product:update:team")
  @UseInterceptors(
    FileInterceptor("file", { limits: { fileSize: 50 * 1024 * 1024 } }),
  )
  uploadAsset(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @UploadedFile()
    file: {
      buffer: Buffer;
      originalname: string;
      mimetype: string;
      size: number;
    },
    @Body() dto: CreateProductAssetDto,
  ) {
    if (!file) throw new BadRequestException("请上传媒体文件");
    return this.service.uploadAsset(user, id, file, dto);
  }

  @Patch(":id/assets/:assetId")
  @RequirePermission("product:update:team")
  updateAsset(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Param("assetId") assetId: string,
    @Body() dto: UpdateProductAssetDto,
  ) {
    return this.service.updateAsset(user, id, assetId, dto);
  }

  @Delete(":id/assets/:assetId")
  @RequirePermission("product:update:team")
  deleteAsset(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Param("assetId") assetId: string,
  ) {
    return this.service.deleteAsset(user, id, assetId);
  }

  @Get(":id/assets/:assetId/content")
  @RequirePermission("product:read:team")
  @Header("Cache-Control", "private, max-age=3600")
  async assetContent(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Param("assetId") assetId: string,
    @Res() response: Response,
  ) {
    const asset = await this.service.getAssetForRead(user, id, assetId);
    response.setHeader("Content-Type", asset.mimeType);
    response.setHeader("Content-Length", asset.byteSize);
    response.setHeader(
      "Content-Disposition",
      `inline; filename="${asset.originalName ?? "asset"}"`,
    );
    this.service.mediaStream(asset.storageKey).pipe(response);
  }

  private parseTake(value?: string) {
    if (value === undefined || value.trim() === "") return undefined;
    const take = Number(value);
    if (!Number.isInteger(take) || take < 1) {
      throw new BadRequestException("take 必须是大于 0 的整数");
    }
    return take;
  }
}
