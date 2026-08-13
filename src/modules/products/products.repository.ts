import { Injectable } from "@nestjs/common";

import { PrismaService } from "../../common/database/prisma.service";

@Injectable()
export class ProductsRepository {
  constructor(private readonly prisma: PrismaService) {}

  findById(id: string) {
    return this.prisma.product.findUnique({
      where: { id },
      include: {
        variants: true,
        assets: true,
        team: true,
      },
    });
  }

  findAsset(productId: string, assetId: string) {
    return this.prisma.productAsset.findFirst({
      where: { id: assetId, productId },
    });
  }

  findAssets(productId: string, assetIds: string[]) {
    return this.prisma.productAsset.findMany({
      where: { productId, id: { in: assetIds } },
      orderBy: { createdAt: "asc" },
    });
  }

  list(where: Record<string, unknown>, take: number, cursor?: string) {
    return this.prisma.product.findMany({
      where,
      take: take + 1,
      ...(cursor ? { skip: 1, cursor: { id: cursor } } : {}),
      orderBy: { createdAt: "desc" },
      include: { team: true, variants: true },
    });
  }

  create(data: Record<string, unknown>) {
    return this.prisma.product.create({
      data: data as never,
      include: { team: true, variants: true },
    });
  }

  update(id: string, data: Record<string, unknown>) {
    return this.prisma.product.update({
      where: { id },
      data: data as never,
      include: { team: true, variants: true },
    });
  }

  createVariant(productId: string, data: Record<string, unknown>) {
    return this.prisma.productVariant.create({
      data: { productId, ...data } as never,
    });
  }

  createAsset(data: Record<string, unknown>) {
    return this.prisma.productAsset.create({
      data: data as never,
    });
  }

  updateAsset(id: string, data: Record<string, unknown>) {
    return this.prisma.productAsset.update({
      where: { id },
      data: data as never,
    });
  }

  deleteAsset(id: string) {
    return this.prisma.productAsset.delete({ where: { id } });
  }
}
