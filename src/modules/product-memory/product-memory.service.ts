import { Injectable } from "@nestjs/common";

import { AppError } from "../../common/errors/app-error";
import { PrismaService } from "../../common/database/prisma.service";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { ProductsService } from "../products/products.service";
import { SaveMemoryDto } from "./dto/save-memory.dto";

@Injectable()
export class ProductMemoryService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly products: ProductsService,
    private readonly rbac: RbacService,
  ) {}

  async get(user: AuthenticatedUser, productId: string) {
    const product = await this.products.getById(user, productId);
    const [facts, brandVisual, generationRules, forbiddenRules, latestVersion] =
      await Promise.all([
        this.prisma.productFact.findMany({
          where: { productId },
          orderBy: { key: "asc" },
        }),
        this.prisma.brandMemory.findMany({
          where: { productId },
          orderBy: { key: "asc" },
        }),
        this.prisma.generationRule.findMany({
          where: { productId },
          orderBy: { priority: "desc" },
        }),
        this.prisma.forbiddenRule.findMany({
          where: { productId },
          orderBy: { createdAt: "asc" },
        }),
        this.prisma.productMemoryVersion.findFirst({
          where: { productId },
          orderBy: { version: "desc" },
        }),
      ]);
    return {
      data: {
        product: product.data,
        facts,
        brandVisual,
        generationRules,
        forbiddenRules,
        latestVersion,
      },
    };
  }

  /**
   * 目的：保存产品记忆，并生成不可变版本快照。
   * 输入：产品、当前用户和分层记忆内容。
   * 输出：新的 ProductMemoryVersion。
   * 业务错误：产品不存在或无团队编辑权限。
   * 外部副作用：一个数据库事务内更新记忆表并创建版本。
   * 幂等性：版本号由数据库事务内计算；相同提交可产生新版本。
   */
  async save(user: AuthenticatedUser, productId: string, dto: SaveMemoryDto) {
    const product = await this.products.getById(user, productId);
    this.rbac.assertPermission(user, "memory:update:team");

    const snapshot = {
      facts: dto.facts,
      brandVisual: dto.brandVisual,
      generationRules: dto.generationRules,
      forbiddenRules: dto.forbiddenRules,
      notes: dto.notes ?? null,
    };

    const version = await this.prisma.$transaction(async (tx) => {
      await tx.productFact.deleteMany({ where: { productId } });
      await tx.brandMemory.deleteMany({ where: { productId } });
      await tx.generationRule.deleteMany({ where: { productId } });
      await tx.forbiddenRule.deleteMany({ where: { productId } });

      if (dto.facts.length) {
        await tx.productFact.createMany({
          data: dto.facts.map((item) => ({
            productId,
            key: item.key.trim(),
            value: item.value.trim(),
            source: item.source?.trim(),
          })),
        });
      }
      if (dto.brandVisual.length) {
        await tx.brandMemory.createMany({
          data: dto.brandVisual.map((item) => ({
            productId,
            key: item.key.trim(),
            value: item.value.trim(),
          })),
        });
      }
      if (dto.generationRules.length) {
        await tx.generationRule.createMany({
          data: dto.generationRules.map((rule, index) => ({
            productId,
            rule: rule.trim(),
            priority: dto.generationRules.length - index,
          })),
        });
      }
      if (dto.forbiddenRules.length) {
        await tx.forbiddenRule.createMany({
          data: dto.forbiddenRules.map((rule) => ({
            productId,
            rule: rule.trim(),
          })),
        });
      }
      const latest = await tx.productMemoryVersion.findFirst({
        where: { productId },
        orderBy: { version: "desc" },
        select: { version: true },
      });
      return tx.productMemoryVersion.create({
        data: {
          productId,
          version: (latest?.version ?? 0) + 1,
          snapshot,
          createdById: user.id,
        },
      });
    });

    if (!version)
      throw new AppError("MEMORY_SAVE_FAILED", "产品记忆保存失败", 500);
    return { data: version };
  }

  async latestSnapshot(user: AuthenticatedUser, productId: string) {
    const memory = await this.get(user, productId);
    const data = memory.data;
    return {
      facts: data.facts.map((item) => `${item.key}: ${item.value}`),
      brandVisual: data.brandVisual.map((item) => `${item.key}: ${item.value}`),
      generationRules: data.generationRules.map((item) => item.rule),
      forbiddenRules: data.forbiddenRules.map((item) => item.rule),
      version: data.latestVersion?.version ?? 0,
    };
  }
}
