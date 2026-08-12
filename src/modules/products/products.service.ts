import { Injectable } from "@nestjs/common";
import { ProductStatus } from "@prisma/client";

import { AppError } from "../../common/errors/app-error";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { CreateProductDto } from "./dto/create-product.dto";
import { CreateVariantDto } from "./dto/create-variant.dto";
import { UpdateProductDto } from "./dto/update-product.dto";
import { ProductsRepository } from "./products.repository";

@Injectable()
export class ProductsService {
  constructor(
    private readonly repository: ProductsRepository,
    private readonly rbac: RbacService,
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
    return { data: product };
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
    return {
      data: await this.repository.create({
        name: dto.name.trim(),
        code: dto.code.trim().toUpperCase(),
        brand: dto.brand?.trim(),
        category: dto.category?.trim(),
        description: dto.description?.trim(),
        createdById: user.id,
        ownerId: user.id,
        teamId: user.teamIds[0],
        status: ProductStatus.DRAFT,
      }),
    };
  }

  async update(user: AuthenticatedUser, id: string, dto: UpdateProductDto) {
    const existing = await this.repository.findById(id);
    this.assertReadable(user, existing);
    this.rbac.assertPermission(user, "product:update:team");
    return {
      data: await this.repository.update(id, {
        ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
        ...(dto.code === undefined
          ? {}
          : { code: dto.code.trim().toUpperCase() }),
        ...(dto.brand === undefined ? {} : { brand: dto.brand?.trim() }),
        ...(dto.category === undefined
          ? {}
          : { category: dto.category?.trim() }),
        ...(dto.description === undefined
          ? {}
          : { description: dto.description?.trim() }),
      }),
    };
  }

  async createVariant(
    user: AuthenticatedUser,
    productId: string,
    dto: CreateVariantDto,
  ) {
    const product = await this.repository.findById(productId);
    this.assertReadable(user, product);
    this.rbac.assertPermission(user, "product:update:team");
    return {
      data: await this.repository.createVariant(productId, {
        sku: dto.sku.trim().toUpperCase(),
        name: dto.name?.trim(),
        color: dto.color?.trim(),
        size: dto.size?.trim(),
        material: dto.material?.trim(),
      }),
    };
  }

  assertReadable(
    user: AuthenticatedUser,
    product: {
      id: string;
      createdById: string;
      ownerId: string | null;
      teamId: string | null;
    } | null,
  ): asserts product is {
    id: string;
    createdById: string;
    ownerId: string | null;
    teamId: string | null;
  } {
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
