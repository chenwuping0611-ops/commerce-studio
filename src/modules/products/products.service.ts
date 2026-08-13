import { Injectable } from "@nestjs/common";
import {
  AssetReviewStatus,
  ProductStatus,
  type ProductAsset,
} from "@prisma/client";

import { AuditService } from "../../common/audit/audit.service";
import { AppError } from "../../common/errors/app-error";
import {
  MediaService,
  type UploadedMedia,
} from "../../common/media/media.service";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { CreateProductAssetDto } from "./dto/create-product-asset.dto";
import { CreateProductDto } from "./dto/create-product.dto";
import { CreateVariantDto } from "./dto/create-variant.dto";
import { UpdateProductAssetDto } from "./dto/update-product-asset.dto";
import { UpdateProductDto } from "./dto/update-product.dto";
import { ProductsRepository } from "./products.repository";

@Injectable()
export class ProductsService {
  constructor(
    private readonly repository: ProductsRepository,
    private readonly rbac: RbacService,
    private readonly media: MediaService,
    private readonly audit: AuditService,
  ) {}

  /**
   * 目的：按当前用户的数据范围列出产品。
   * 输入：当前用户、分页大小和游标。
   * 输出：产品列表和下一页游标。
   * 业务错误：无权限时由调用方拦截。
   * 外部副作用：无。
   */
  async list(user: AuthenticatedUser, take = 20, cursor?: string) {
    const boundedTake = Math.min(Math.max(take, 1), 100);
    const where = this.rbac.isSystemAdmin(user)
      ? {}
      : {
          OR: [
            { createdById: user.id },
            { ownerId: user.id },
            { teamId: { in: user.teamIds } },
          ],
        };
    const rows = await this.repository.list(where, boundedTake, cursor);
    const hasNext = rows.length > boundedTake;
    const data = hasNext ? rows.slice(0, boundedTake) : rows;
    return {
      data,
      meta: {
        nextCursor: hasNext ? (data[data.length - 1]?.id ?? null) : null,
      },
    };
  }

  async getById(user: AuthenticatedUser, id: string) {
    const product = await this.repository.findById(id);
    this.assertReadable(user, product);
    return { data: this.toPublicProduct(product) };
  }

  /**
   * 目的：创建产品并绑定当前用户的默认团队。
   * 输入：当前用户和产品基础信息。
   * 输出：持久化后的产品。
   * 业务错误：产品编码重复或用户没有产品创建权限。
   * 外部副作用：数据库写入。
   * 幂等性：由产品编码唯一约束提供重复保护。
   */
  async create(user: AuthenticatedUser, dto: CreateProductDto) {
    this.rbac.assertPermission(user, "product:update:team");
    const product = await this.repository.create({
      name: dto.name.trim(),
      code: dto.code.trim().toUpperCase(),
      brand: dto.brand?.trim(),
      category: dto.category?.trim(),
      description: dto.description?.trim(),
      createdById: user.id,
      ownerId: user.id,
      teamId: user.teamIds[0],
      status: ProductStatus.DRAFT,
    });
    await this.audit.record({
      actorId: user.id,
      action: "product.create",
      resource: "Product",
      resourceId: product.id,
      metadata: { code: product.code },
    });
    return { data: product };
  }

  async update(user: AuthenticatedUser, id: string, dto: UpdateProductDto) {
    const existing = await this.repository.findById(id);
    this.assertReadable(user, existing);
    this.rbac.assertPermission(user, "product:update:team");
    const product = await this.repository.update(id, {
      ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
      ...(dto.code === undefined
        ? {}
        : { code: dto.code.trim().toUpperCase() }),
      ...(dto.brand === undefined ? {} : { brand: dto.brand?.trim() }),
      ...(dto.category === undefined ? {} : { category: dto.category?.trim() }),
      ...(dto.description === undefined
        ? {}
        : { description: dto.description?.trim() }),
    });
    await this.audit.record({
      actorId: user.id,
      action: "product.update",
      resource: "Product",
      resourceId: id,
      metadata: { code: product.code },
    });
    return { data: product };
  }

  async createVariant(
    user: AuthenticatedUser,
    productId: string,
    dto: CreateVariantDto,
  ) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    this.rbac.assertPermission(user, "product:update:team");
    const variant = await this.repository.createVariant(productId, {
      sku: dto.sku.trim().toUpperCase(),
      name: dto.name?.trim(),
      color: dto.color?.trim(),
      size: dto.size?.trim(),
      material: dto.material?.trim(),
    });
    await this.audit.record({
      actorId: user.id,
      action: "product.variant.create",
      resource: "ProductVariant",
      resourceId: variant.id,
      metadata: { productId },
    });
    return { data: variant };
  }

  async listAssets(user: AuthenticatedUser, productId: string) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    return {
      data: product.assets.map((asset) => this.toPublicAsset(productId, asset)),
    };
  }

  async validateAssetReferences(
    user: AuthenticatedUser,
    productId: string,
    assetIds: string[],
  ) {
    if (assetIds.length === 0) return [];
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    const normalizedIds = [
      ...new Set(assetIds.map((assetId) => assetId.trim()).filter(Boolean)),
    ];
    const assets = await this.repository.findAssets(productId, normalizedIds);
    if (assets.length !== normalizedIds.length) {
      throw new AppError(
        "PRODUCT_ASSET_REFERENCE_INVALID",
        "输入素材必须属于当前产品",
        400,
      );
    }
    return normalizedIds;
  }

  /**
   * 目的：把已持久化的产品素材 ID 转换为供应商可读取的短期地址。
   * 输入：产品 ID 和任务快照中的素材 ID。
   * 输出：带签名、限时的素材 URL。
   * 安全边界：只返回属于当前产品的素材，不接受外部任意路径。
   */
  async providerAssetUrls(productId: string, assetIds: string[]) {
    if (assetIds.length === 0) return [];
    const normalizedIds = [
      ...new Set(assetIds.map((assetId) => assetId.trim()).filter(Boolean)),
    ];
    const assets = await this.repository.findAssets(productId, normalizedIds);
    if (assets.length !== normalizedIds.length) {
      throw new AppError(
        "PRODUCT_ASSET_REFERENCE_INVALID",
        "任务引用的产品素材不存在",
        409,
      );
    }
    return normalizedIds.map((assetId) =>
      this.media.providerAssetUrl(productId, assetId),
    );
  }

  async uploadAsset(
    user: AuthenticatedUser,
    productId: string,
    file: UploadedMedia,
    dto: CreateProductAssetDto,
  ) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    this.rbac.assertPermission(user, "product:update:team");
    if (
      dto.variantId &&
      !product.variants.some((variant) => variant.id === dto.variantId)
    ) {
      throw new AppError(
        "PRODUCT_VARIANT_NOT_FOUND",
        "素材关联的 SKU 不属于当前产品",
        400,
      );
    }
    const stored = await this.media.saveUpload(productId, file);
    try {
      const asset = await this.repository.createAsset({
        productId,
        variantId: dto.variantId,
        type: dto.type?.trim() || "PRODUCT_REFERENCE",
        view: dto.view?.trim(),
        storageKey: stored.storageKey,
        originalName: stored.originalName,
        mimeType: stored.mimeType,
        byteSize: stored.byteSize,
        sha256: stored.sha256,
        reviewStatus: AssetReviewStatus.PENDING,
        createdById: user.id,
      });
      await this.audit.record({
        actorId: user.id,
        action: "product.asset.upload",
        resource: "ProductAsset",
        resourceId: asset.id,
        metadata: {
          productId,
          mimeType: asset.mimeType,
          byteSize: asset.byteSize,
        },
      });
      return {
        data: this.toPublicAsset(productId, asset),
      };
    } catch (error) {
      await this.media.remove(stored.storageKey);
      throw error;
    }
  }

  async updateAsset(
    user: AuthenticatedUser,
    productId: string,
    assetId: string,
    dto: UpdateProductAssetDto,
  ) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    this.rbac.assertPermission(user, "product:update:team");
    const asset = await this.repository.findAsset(productId, assetId);
    if (!asset)
      throw new AppError("PRODUCT_ASSET_NOT_FOUND", "产品素材不存在", 404);
    const updated = await this.repository.updateAsset(assetId, {
      ...(dto.type === undefined ? {} : { type: dto.type.trim() }),
      ...(dto.view === undefined ? {} : { view: dto.view?.trim() }),
      ...(dto.reviewStatus === undefined
        ? {}
        : { reviewStatus: dto.reviewStatus }),
    });
    await this.audit.record({
      actorId: user.id,
      action: "product.asset.update",
      resource: "ProductAsset",
      resourceId: assetId,
      metadata: { productId },
    });
    return {
      data: this.toPublicAsset(productId, updated),
    };
  }

  async deleteAsset(
    user: AuthenticatedUser,
    productId: string,
    assetId: string,
  ) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    this.rbac.assertPermission(user, "product:update:team");
    const asset = await this.repository.findAsset(productId, assetId);
    if (!asset)
      throw new AppError("PRODUCT_ASSET_NOT_FOUND", "产品素材不存在", 404);
    await this.repository.deleteAsset(assetId);
    await this.media.remove(asset.storageKey);
    await this.audit.record({
      actorId: user.id,
      action: "product.asset.delete",
      resource: "ProductAsset",
      resourceId: assetId,
      metadata: { productId },
    });
    return { data: { deleted: true } };
  }

  async getAssetForRead(
    user: AuthenticatedUser,
    productId: string,
    assetId: string,
  ) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    const asset = await this.repository.findAsset(productId, assetId);
    if (!asset)
      throw new AppError("PRODUCT_ASSET_NOT_FOUND", "产品素材不存在", 404);
    return asset;
  }

  mediaStream(storageKey: string) {
    return this.media.createReadStream(storageKey);
  }

  private toPublicProduct<
    T extends {
      assets?: ProductAsset[];
    },
  >(product: T) {
    return {
      ...product,
      ...(product.assets
        ? {
            assets: product.assets.map((asset) =>
              this.toPublicAsset(asset.productId, asset),
            ),
          }
        : {}),
    };
  }

  private toPublicAsset(productId: string, asset: ProductAsset) {
    return {
      id: asset.id,
      productId: asset.productId,
      variantId: asset.variantId,
      type: asset.type,
      view: asset.view,
      originalName: asset.originalName,
      mimeType: asset.mimeType,
      byteSize: asset.byteSize,
      sha256: asset.sha256,
      reviewStatus: asset.reviewStatus,
      createdById: asset.createdById,
      createdAt: asset.createdAt,
      updatedAt: asset.updatedAt,
      url: this.media.relativeAssetUrl(productId, asset.id),
    };
  }

  assertReadable<
    T extends {
      id: string;
      createdById: string;
      ownerId: string | null;
      teamId: string | null;
    },
  >(user: AuthenticatedUser, product: T | null): asserts product is T {
    if (!product) throw new AppError("PRODUCT_NOT_FOUND", "产品不存在", 404);
    const readable =
      this.rbac.isSystemAdmin(user) ||
      product.createdById === user.id ||
      product.ownerId === user.id ||
      (product.teamId ? user.teamIds.includes(product.teamId) : false);
    if (!readable) {
      throw new AppError("RBAC_PRODUCT_SCOPE_DENIED", "无权访问该产品", 403);
    }
  }
}
