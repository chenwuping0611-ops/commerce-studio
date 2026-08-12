import { Injectable } from "@nestjs/common";
import { Prisma, TaskStatus } from "@prisma/client";

import { AppError } from "../../common/errors/app-error";
import type { AuthenticatedUser } from "../auth/auth.types";
import { ProductsService } from "../products/products.service";
import { RbacService } from "../rbac/rbac.service";
import { CreateCanvasDto } from "./dto/create-canvas.dto";
import { UpdateCanvasDto } from "./dto/update-canvas.dto";
import { PrismaService } from "../../common/database/prisma.service";

const emptyNodes: Array<Record<string, unknown>> = [];
const emptyEdges: Array<Record<string, unknown>> = [];
const defaultViewport = { x: 0, y: 0, zoom: 1 };

@Injectable()
export class CanvasService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly products: ProductsService,
    private readonly rbac: RbacService,
  ) {}

  list(user: AuthenticatedUser) {
    return this.prisma.canvasDocument
      .findMany({
        where: this.scope(user),
        orderBy: { updatedAt: "desc" },
        include: { product: { select: { id: true, name: true, code: true } } },
      })
      .then((rows) => ({ data: rows }));
  }

  async get(user: AuthenticatedUser, id: string) {
    const canvas = await this.prisma.canvasDocument.findUnique({
      where: { id },
      include: {
        product: true,
        revisions: { orderBy: { version: "desc" }, take: 10 },
      },
    });
    this.assertReadable(user, canvas);
    return { data: canvas };
  }

  /**
   * 目的：创建一个只保存业务引用的 React Flow Canvas 文档。
   * 输入：当前用户、名称、产品引用和节点/边初始数据。
   * 输出：CanvasDocument。
   * 外部副作用：数据库写入；不调用模型 API。
   * 安全边界：节点 data 不允许保存 API Key 或媒体二进制。
   */
  async create(user: AuthenticatedUser, dto: CreateCanvasDto) {
    this.rbac.assertPermission(user, "canvas:manage:team");
    if (dto.productId) await this.products.getById(user, dto.productId);
    const canvas = await this.prisma.canvasDocument.create({
      data: {
        name: dto.name.trim(),
        productId: dto.productId,
        createdById: user.id,
        teamId: user.teamIds[0],
        nodes: this.toInputJson(this.sanitizeGraph(dto.nodes ?? emptyNodes)),
        edges: this.toInputJson(this.sanitizeGraph(dto.edges ?? emptyEdges)),
        viewport: this.toInputJson(dto.viewport ?? defaultViewport),
        settings: this.toInputJson(dto.settings ?? {}),
      },
    });
    return { data: canvas };
  }

  async update(user: AuthenticatedUser, id: string, dto: UpdateCanvasDto) {
    const current = await this.prisma.canvasDocument.findUnique({
      where: { id },
    });
    if (!current) throw new AppError("CANVAS_NOT_FOUND", "Canvas 不存在", 404);
    this.assertReadable(user, current);
    this.rbac.assertPermission(user, "canvas:manage:team");
    if (dto.productId) await this.products.getById(user, dto.productId);
    const nextVersion = current.version + 1;
    const nodes = this.toInputJson(
      dto.nodes ? this.sanitizeGraph(dto.nodes) : current.nodes,
    );
    const edges = this.toInputJson(
      dto.edges ? this.sanitizeGraph(dto.edges) : current.edges,
    );
    const viewport = this.toInputJson(dto.viewport ?? current.viewport);
    const updated = await this.prisma.$transaction(async (tx) => {
      const row = await tx.canvasDocument.update({
        where: { id },
        data: {
          ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
          ...(dto.productId === undefined ? {} : { productId: dto.productId }),
          version: nextVersion,
          nodes,
          edges,
          viewport,
          ...(dto.settings === undefined
            ? {}
            : { settings: this.toInputJson(dto.settings) }),
        },
      });
      await tx.canvasRevision.create({
        data: {
          canvasId: id,
          version: nextVersion,
          nodes,
          edges,
          viewport,
          createdById: user.id,
          summary: "Canvas 自动保存",
        },
      });
      return row;
    });
    return { data: updated };
  }

  async execute(user: AuthenticatedUser, id: string) {
    const canvas = await this.get(user, id);
    const snapshot = {
      canvasId: id,
      version: canvas.data?.version,
      nodes: canvas.data?.nodes,
      edges: canvas.data?.edges,
      viewport: canvas.data?.viewport,
    };
    const execution = await this.prisma.canvasExecution.create({
      data: {
        canvasId: id,
        version: Number(canvas.data?.version ?? 1),
        snapshot: this.toInputJson(snapshot),
        taskIds: [],
        status: TaskStatus.CREATED,
      },
    });
    return {
      data: execution,
      meta: {
        message: "Canvas 执行快照已创建；模型任务将在后续节点编译阶段提交。",
      },
    };
  }

  private scope(user: AuthenticatedUser) {
    if (this.rbac.isSystemAdmin(user)) return {};
    return {
      OR: [{ createdById: user.id }, { teamId: { in: user.teamIds } }],
    };
  }

  private assertReadable(
    user: AuthenticatedUser,
    canvas: { createdById: string; teamId: string | null } | null,
  ) {
    if (!canvas) throw new AppError("CANVAS_NOT_FOUND", "Canvas 不存在", 404);
    const readable =
      this.rbac.isSystemAdmin(user) ||
      canvas.createdById === user.id ||
      (canvas.teamId ? user.teamIds.includes(canvas.teamId) : false);
    if (!readable)
      throw new AppError("RBAC_CANVAS_SCOPE_DENIED", "无权访问该 Canvas", 403);
  }

  private sanitizeGraph(items: Array<Record<string, unknown>>) {
    const serialized = JSON.stringify(items);
    if (serialized.length > 2_000_000) {
      throw new AppError(
        "CANVAS_GRAPH_TOO_LARGE",
        "Canvas 数据超过大小限制",
        413,
      );
    }
    return items.map((item) => {
      const data = (item.data ?? {}) as Record<string, unknown>;
      const safeData = { ...data };
      for (const key of [
        "apiKey",
        "apiKeyEncrypted",
        "secret",
        "token",
        "binary",
        "base64",
      ]) {
        delete safeData[key];
      }
      return { ...item, data: safeData };
    });
  }

  private toInputJson(value: unknown): Prisma.InputJsonValue {
    return JSON.parse(JSON.stringify(value ?? {})) as Prisma.InputJsonValue;
  }
}
