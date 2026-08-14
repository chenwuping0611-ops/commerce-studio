import { Injectable } from "@nestjs/common";
import { Prisma } from "@prisma/client";

import { AuditService } from "../../common/audit/audit.service";
import { PrismaService } from "../../common/database/prisma.service";
import { AppError } from "../../common/errors/app-error";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { CreateSkillDto } from "./dto/create-skill.dto";
import { UpdateSkillDto } from "./dto/update-skill.dto";

const supportedTypes = ["IMAGE", "VIDEO", "BOTH"] as const;
type SkillMediaType = (typeof supportedTypes)[number];

@Injectable()
export class SkillsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly rbac: RbacService,
    private readonly audit: AuditService,
  ) {}

  async list(user: AuthenticatedUser, mediaType?: "IMAGE" | "VIDEO") {
    this.assertReadable(user);
    const rows = await this.prisma.skillProfile.findMany({
      where: {
        enabled: true,
        ...(mediaType ? { mediaType: { in: [mediaType, "BOTH"] } } : {}),
      },
      orderBy: [{ updatedAt: "desc" }, { createdAt: "desc" }],
    });
    return { data: rows.map((row) => this.toPublic(row)) };
  }

  async listForAdmin(user: AuthenticatedUser) {
    this.rbac.assertPermission(user, "model_config:read:system");
    const rows = await this.prisma.skillProfile.findMany({
      orderBy: [{ enabled: "desc" }, { updatedAt: "desc" }],
    });
    return { data: rows.map((row) => this.toPublic(row)) };
  }

  async create(user: AuthenticatedUser, dto: CreateSkillDto) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const row = await this.prisma.skillProfile.create({
      data: this.toWriteData(user.id, dto),
    });
    await this.audit.record({
      actorId: user.id,
      action: "skill.create",
      resource: "SkillProfile",
      resourceId: row.id,
      metadata: { code: row.code, mediaType: row.mediaType },
    });
    return { data: this.toPublic(row) };
  }

  async update(user: AuthenticatedUser, id: string, dto: UpdateSkillDto) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const existing = await this.prisma.skillProfile.findUnique({
      where: { id },
    });
    if (!existing) {
      throw new AppError("SKILL_NOT_FOUND", "Skill 不存在", 404);
    }
    const row = await this.prisma.skillProfile.update({
      where: { id },
      data: {
        ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
        ...(dto.code === undefined
          ? {}
          : { code: this.normalizeCode(dto.code) }),
        ...(dto.mediaType === undefined ? {} : { mediaType: dto.mediaType }),
        ...(dto.description === undefined
          ? {}
          : { description: dto.description?.trim() || null }),
        ...(dto.version === undefined
          ? {}
          : { version: dto.version?.trim() || null }),
        ...(dto.tags === undefined ? {} : { tags: this.jsonValue(dto.tags) }),
        ...(dto.promptTemplate === undefined
          ? {}
          : { promptTemplate: dto.promptTemplate?.trim() || null }),
        ...(dto.negativePrompt === undefined
          ? {}
          : { negativePrompt: dto.negativePrompt?.trim() || null }),
        ...(dto.settings === undefined
          ? {}
          : { settings: this.jsonValue(dto.settings) }),
        ...(dto.enabled === undefined ? {} : { enabled: dto.enabled }),
      },
    });
    await this.audit.record({
      actorId: user.id,
      action: "skill.update",
      resource: "SkillProfile",
      resourceId: row.id,
      metadata: { code: row.code, mediaType: row.mediaType },
    });
    return { data: this.toPublic(row) };
  }

  async disable(user: AuthenticatedUser, id: string) {
    this.rbac.assertPermission(user, "model_config:update:system");
    const row = await this.prisma.skillProfile.update({
      where: { id },
      data: { enabled: false },
    });
    await this.audit.record({
      actorId: user.id,
      action: "skill.disable",
      resource: "SkillProfile",
      resourceId: id,
      metadata: { code: row.code },
    });
    return { data: { disabled: true } };
  }

  async getForGeneration(
    user: AuthenticatedUser,
    id: string,
    mediaType: "IMAGE" | "VIDEO",
  ) {
    this.rbac.assertPermission(user, "generation:create:team");
    const row = await this.prisma.skillProfile.findUnique({ where: { id } });
    if (
      !row ||
      !row.enabled ||
      (row.mediaType !== "BOTH" && row.mediaType !== mediaType)
    ) {
      throw new AppError(
        "SKILL_UNAVAILABLE",
        "当前 Skill 不可用于此生成类型",
        409,
      );
    }
    return row;
  }

  private assertReadable(user: AuthenticatedUser) {
    if (
      !this.rbac.hasPermission(user, "generation:create:team") &&
      !this.rbac.hasPermission(user, "model_config:read:system")
    ) {
      throw new AppError(
        "RBAC_SKILL_READ_DENIED",
        "没有查看 Skill 的权限",
        403,
      );
    }
  }

  private toWriteData(userId: string, dto: CreateSkillDto) {
    return {
      name: dto.name.trim(),
      code: this.normalizeCode(dto.code),
      mediaType: dto.mediaType as SkillMediaType,
      description: dto.description?.trim() || null,
      version: dto.version?.trim() || null,
      tags: this.jsonValue(dto.tags ?? []),
      promptTemplate: dto.promptTemplate?.trim() || null,
      negativePrompt: dto.negativePrompt?.trim() || null,
      settings: this.jsonValue(dto.settings ?? {}),
      enabled: dto.enabled ?? true,
      createdById: userId,
    };
  }

  private normalizeCode(value: string) {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, "-");
  }

  private jsonValue(value: unknown) {
    return JSON.parse(JSON.stringify(value)) as Prisma.InputJsonValue;
  }

  private toPublic(row: {
    id: string;
    name: string;
    code: string;
    mediaType: string;
    description: string | null;
    version: string | null;
    tags: Prisma.JsonValue | null;
    promptTemplate: string | null;
    negativePrompt: string | null;
    settings: Prisma.JsonValue | null;
    enabled: boolean;
    createdAt: Date;
    updatedAt: Date;
  }) {
    return row;
  }
}
