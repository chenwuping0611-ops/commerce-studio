import { Injectable } from "@nestjs/common";
import { UserStatus } from "@prisma/client";
import bcrypt from "bcryptjs";

import { AuditService } from "../../common/audit/audit.service";
import { PrismaService } from "../../common/database/prisma.service";
import { AppError } from "../../common/errors/app-error";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacService } from "../rbac/rbac.service";
import { AddTeamMemberDto } from "./dto/add-team-member.dto";
import { CreateTeamDto } from "./dto/create-team.dto";
import { CreateUserDto } from "./dto/create-user.dto";
import { ResetPasswordDto } from "./dto/reset-password.dto";
import { UpdateProfileDto } from "./dto/update-profile.dto";
import { UpdateRolePermissionsDto } from "./dto/update-role-permissions.dto";
import { UpdateSettingDto } from "./dto/update-setting.dto";
import { UpdateTeamDto } from "./dto/update-team.dto";
import { UpdateUserDto } from "./dto/update-user.dto";

@Injectable()
export class SystemService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly rbac: RbacService,
    private readonly audit: AuditService,
  ) {}

  async updateProfile(
    user: AuthenticatedUser,
    dto: UpdateProfileDto,
    requestId?: string,
  ) {
    if (dto.newPassword && !dto.currentPassword) {
      throw new AppError(
        "AUTH_PASSWORD_CONFIRMATION_REQUIRED",
        "修改密码必须提供当前密码",
        400,
      );
    }
    if (dto.newPassword) {
      const current = await this.prisma.user.findUnique({
        where: { id: user.id },
        select: { passwordHash: true },
      });
      if (
        !current ||
        !(await bcrypt.compare(dto.currentPassword!, current.passwordHash))
      ) {
        throw new AppError(
          "AUTH_CURRENT_PASSWORD_INVALID",
          "当前密码不正确",
          400,
        );
      }
    }
    const updated = await this.prisma.user.update({
      where: { id: user.id },
      data: {
        ...(dto.displayName === undefined
          ? {}
          : { displayName: dto.displayName.trim() }),
        ...(dto.newPassword
          ? { passwordHash: await bcrypt.hash(dto.newPassword, 12) }
          : {}),
      },
    });
    await this.audit.record({
      actorId: user.id,
      action: "profile.update",
      resource: "User",
      resourceId: user.id,
      requestId,
      metadata: { passwordChanged: Boolean(dto.newPassword) },
    });
    return { data: this.toUserSummary(updated) };
  }

  async listUsers(user: AuthenticatedUser) {
    this.assertSystem(user, "user:manage:system");
    const rows = await this.prisma.user.findMany({
      orderBy: { createdAt: "desc" },
      include: {
        userRoles: { include: { role: true } },
        teamMemberships: { include: { team: true } },
      },
    });
    return {
      data: rows.map((row) => ({
        ...this.toUserSummary(row),
        roles: row.userRoles.map(({ role }) => role),
        teams: row.teamMemberships.map(({ team, isLead }) => ({
          ...team,
          isLead,
        })),
      })),
    };
  }

  async createUser(
    actor: AuthenticatedUser,
    dto: CreateUserDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    const roleIds = dto.roleIds ?? [];
    const teamIds = dto.teamIds ?? [];
    const user = await this.prisma.user.create({
      data: {
        email: dto.email.toLowerCase().trim(),
        displayName: dto.displayName.trim(),
        passwordHash: await bcrypt.hash(dto.password, 12),
        status: dto.status ?? UserStatus.ACTIVE,
        userRoles: roleIds.length
          ? { create: roleIds.map((roleId) => ({ roleId })) }
          : undefined,
        teamMemberships: teamIds.length
          ? { create: teamIds.map((teamId) => ({ teamId })) }
          : undefined,
      },
      include: {
        userRoles: { include: { role: true } },
        teamMemberships: { include: { team: true } },
      },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "user.create",
      resource: "User",
      resourceId: user.id,
      requestId,
      metadata: { email: user.email },
    });
    return { data: this.toManagedUser(user) };
  }

  async updateUser(
    actor: AuthenticatedUser,
    id: string,
    dto: UpdateUserDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    if (id === actor.id && dto.status === UserStatus.DISABLED) {
      throw new AppError(
        "RBAC_SELF_DISABLE_DENIED",
        "不能禁用当前登录用户",
        400,
      );
    }
    const existing = await this.prisma.user.findUnique({ where: { id } });
    if (!existing) throw new AppError("USER_NOT_FOUND", "用户不存在", 404);
    const updated = await this.prisma.user.update({
      where: { id },
      data: {
        ...(dto.email === undefined
          ? {}
          : { email: dto.email.toLowerCase().trim() }),
        ...(dto.displayName === undefined
          ? {}
          : { displayName: dto.displayName.trim() }),
        ...(dto.status === undefined ? {} : { status: dto.status }),
        ...(dto.roleIds === undefined
          ? {}
          : {
              userRoles: {
                deleteMany: {},
                create: dto.roleIds.map((roleId) => ({ roleId })),
              },
            }),
        ...(dto.teamIds === undefined
          ? {}
          : {
              teamMemberships: {
                deleteMany: {},
                create: dto.teamIds.map((teamId) => ({ teamId })),
              },
            }),
      },
      include: {
        userRoles: { include: { role: true } },
        teamMemberships: { include: { team: true } },
      },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "user.update",
      resource: "User",
      resourceId: id,
      requestId,
      metadata: {
        emailChanged: dto.email !== undefined,
        statusChanged: dto.status !== undefined,
        rolesChanged: dto.roleIds !== undefined,
        teamsChanged: dto.teamIds !== undefined,
      },
    });
    return { data: this.toManagedUser(updated) };
  }

  async resetPassword(
    actor: AuthenticatedUser,
    id: string,
    dto: ResetPasswordDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    const existing = await this.prisma.user.findUnique({ where: { id } });
    if (!existing) throw new AppError("USER_NOT_FOUND", "用户不存在", 404);
    await this.prisma.user.update({
      where: { id },
      data: { passwordHash: await bcrypt.hash(dto.password, 12) },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "user.password.reset",
      resource: "User",
      resourceId: id,
      requestId,
      metadata: {},
    });
    return { data: { reset: true } };
  }

  async listRoles(user: AuthenticatedUser) {
    this.assertSystem(user, "user:manage:system");
    const [roles, permissions] = await Promise.all([
      this.prisma.role.findMany({
        orderBy: { code: "asc" },
        include: { rolePermissions: { include: { permission: true } } },
      }),
      this.prisma.permission.findMany({ orderBy: { code: "asc" } }),
    ]);
    return {
      data: {
        roles: roles.map((role) => ({
          ...role,
          permissions: role.rolePermissions.map(({ permission }) => permission),
        })),
        permissions,
      },
    };
  }

  async updateRolePermissions(
    actor: AuthenticatedUser,
    roleId: string,
    dto: UpdateRolePermissionsDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    const role = await this.prisma.role.findUnique({ where: { id: roleId } });
    if (!role) throw new AppError("ROLE_NOT_FOUND", "角色不存在", 404);
    await this.prisma.$transaction(async (tx) => {
      await tx.rolePermission.deleteMany({ where: { roleId } });
      if (dto.permissionIds.length) {
        await tx.rolePermission.createMany({
          data: dto.permissionIds.map((permissionId) => ({
            roleId,
            permissionId,
          })),
          skipDuplicates: true,
        });
      }
    });
    await this.audit.record({
      actorId: actor.id,
      action: "role.permissions.update",
      resource: "Role",
      resourceId: roleId,
      requestId,
      metadata: { permissionCount: dto.permissionIds.length },
    });
    return this.listRoles(actor);
  }

  async listTeams(user: AuthenticatedUser) {
    this.assertSystem(user, "user:manage:system");
    const rows = await this.prisma.team.findMany({
      orderBy: { createdAt: "desc" },
      include: {
        members: {
          include: {
            user: { select: { id: true, email: true, displayName: true } },
          },
        },
      },
    });
    return {
      data: rows.map((team) => ({
        ...team,
        members: team.members.map(({ user, isLead, createdAt }) => ({
          ...user,
          isLead,
          createdAt,
        })),
      })),
    };
  }

  async createTeam(
    actor: AuthenticatedUser,
    dto: CreateTeamDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    const team = await this.prisma.team.create({
      data: { name: dto.name.trim(), code: dto.code.trim().toLowerCase() },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "team.create",
      resource: "Team",
      resourceId: team.id,
      requestId,
      metadata: { code: team.code },
    });
    return { data: team };
  }

  async updateTeam(
    actor: AuthenticatedUser,
    id: string,
    dto: UpdateTeamDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    const team = await this.prisma.team.update({
      where: { id },
      data: {
        ...(dto.name === undefined ? {} : { name: dto.name.trim() }),
        ...(dto.code === undefined
          ? {}
          : { code: dto.code.trim().toLowerCase() }),
      },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "team.update",
      resource: "Team",
      resourceId: id,
      requestId,
      metadata: {},
    });
    return { data: team };
  }

  async addTeamMember(
    actor: AuthenticatedUser,
    teamId: string,
    dto: AddTeamMemberDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "user:manage:system");
    const membership = await this.prisma.teamMember.upsert({
      where: { userId_teamId: { userId: dto.userId, teamId } },
      update: { isLead: dto.isLead ?? false },
      create: { userId: dto.userId, teamId, isLead: dto.isLead ?? false },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "team.member.upsert",
      resource: "TeamMember",
      resourceId: `${dto.userId}:${teamId}`,
      requestId,
      metadata: { isLead: membership.isLead },
    });
    return { data: membership };
  }

  async listSettings(user: AuthenticatedUser) {
    this.assertSystem(user, "model_config:read:system");
    const rows = await this.prisma.systemSetting.findMany({
      orderBy: { key: "asc" },
    });
    return {
      data: rows.map((row) => ({
        id: row.id,
        key: row.key,
        value: row.isSecret ? null : row.value,
        isSecret: row.isSecret,
        configured: row.isSecret ? true : undefined,
        createdAt: row.createdAt,
        updatedAt: row.updatedAt,
      })),
    };
  }

  async upsertSetting(
    actor: AuthenticatedUser,
    key: string,
    dto: UpdateSettingDto,
    requestId?: string,
  ) {
    this.assertSystem(actor, "model_config:update:system");
    const normalizedKey = key.trim().toLowerCase();
    const existing = await this.prisma.systemSetting.findUnique({
      where: { key: normalizedKey },
    });
    const isSecret = dto.isSecret ?? existing?.isSecret ?? false;
    const row = await this.prisma.systemSetting.upsert({
      where: { key: normalizedKey },
      update: {
        ...(dto.value === null && isSecret
          ? {}
          : { value: dto.value as never }),
        isSecret,
      },
      create: {
        key: normalizedKey,
        value: dto.value as never,
        isSecret,
      },
    });
    await this.audit.record({
      actorId: actor.id,
      action: "system_setting.upsert",
      resource: "SystemSetting",
      resourceId: row.id,
      requestId,
      metadata: { key: normalizedKey, isSecret },
    });
    return {
      data: {
        ...row,
        value: row.isSecret ? null : row.value,
        configured: row.isSecret,
      },
    };
  }

  async listAuditLogs(user: AuthenticatedUser, take = 50) {
    this.assertSystem(user, "audit:read:system");
    const rows = await this.prisma.auditLog.findMany({
      take: Math.min(Math.max(take, 1), 200),
      orderBy: { createdAt: "desc" },
      include: {
        actor: { select: { id: true, email: true, displayName: true } },
      },
    });
    return { data: rows };
  }

  private assertSystem(user: AuthenticatedUser, permission: string) {
    this.rbac.assertPermission(user, permission);
    if (!this.rbac.isSystemAdmin(user)) {
      throw new AppError(
        "RBAC_SYSTEM_SCOPE_DENIED",
        "仅系统管理员可执行此操作",
        403,
      );
    }
  }

  private toUserSummary(user: {
    id: string;
    email: string;
    displayName: string;
    status: UserStatus;
    createdAt: Date;
    updatedAt: Date;
  }) {
    return {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      status: user.status,
      createdAt: user.createdAt,
      updatedAt: user.updatedAt,
    };
  }

  private toManagedUser(user: any) {
    return {
      ...this.toUserSummary(user),
      roles: user.userRoles?.map(({ role }: any) => role) ?? [],
      teams:
        user.teamMemberships?.map(({ team, isLead }: any) => ({
          ...team,
          isLead,
        })) ?? [],
    };
  }
}
