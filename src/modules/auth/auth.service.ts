import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { UserStatus } from "@prisma/client";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";

import { PrismaService } from "../../common/database/prisma.service";
import { AppError } from "../../common/errors/app-error";
import type { AccessTokenPayload, AuthenticatedUser } from "./auth.types";

@Injectable()
export class AuthService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly config: ConfigService,
  ) {}

  /**
   * 目的：校验登录凭据并返回不包含敏感字段的当前用户。
   * 输入：邮箱和明文密码。
   * 输出：认证用户对象。
   * 业务错误：用户不存在、用户已禁用或密码不正确。
   * 外部副作用：无。
   * 幂等性：无写入，重复调用结果一致。
   */
  async validateCredentials(
    email: string,
    password: string,
  ): Promise<AuthenticatedUser> {
    const user = await this.prisma.user.findUnique({
      where: { email: email.toLowerCase().trim() },
      include: {
        userRoles: {
          include: {
            role: {
              include: { rolePermissions: { include: { permission: true } } },
            },
          },
        },
        teamMemberships: true,
      },
    });

    if (!user || user.status !== UserStatus.ACTIVE) {
      throw new AppError("AUTH_INVALID_CREDENTIALS", "邮箱或密码不正确", 401);
    }

    const valid = await bcrypt.compare(password, user.passwordHash);
    if (!valid) {
      throw new AppError("AUTH_INVALID_CREDENTIALS", "邮箱或密码不正确", 401);
    }

    return this.toAuthenticatedUser(user);
  }

  issueToken(user: AuthenticatedUser) {
    const payload: AccessTokenPayload = {
      sub: user.id,
      email: user.email,
      roles: user.roles,
    };
    return jwt.sign(payload, this.jwtSecret(), {
      expiresIn: this.config.get<string>(
        "JWT_EXPIRES_IN",
        "8h",
      ) as jwt.SignOptions["expiresIn"],
    });
  }

  async authenticateToken(token: string): Promise<AuthenticatedUser> {
    let payload: AccessTokenPayload;
    try {
      payload = jwt.verify(token, this.jwtSecret()) as AccessTokenPayload;
    } catch {
      throw new AppError("AUTH_TOKEN_INVALID", "登录状态已失效", 401);
    }

    const user = await this.prisma.user.findUnique({
      where: { id: payload.sub },
      include: {
        userRoles: {
          include: {
            role: {
              include: { rolePermissions: { include: { permission: true } } },
            },
          },
        },
        teamMemberships: true,
      },
    });
    if (!user || user.status !== UserStatus.ACTIVE) {
      throw new AppError("AUTH_USER_UNAVAILABLE", "用户不可用", 401);
    }
    return this.toAuthenticatedUser(user);
  }

  async getCurrentUser(userId: string) {
    const user = await this.prisma.user.findUnique({
      where: { id: userId },
      include: {
        userRoles: {
          include: {
            role: {
              include: { rolePermissions: { include: { permission: true } } },
            },
          },
        },
        teamMemberships: true,
      },
    });
    if (!user) throw new AppError("AUTH_USER_NOT_FOUND", "用户不存在", 404);
    return this.toAuthenticatedUser(user);
  }

  private toAuthenticatedUser(user: any): AuthenticatedUser {
    const roles: string[] = user.userRoles.map((item: any) =>
      String(item.role.code),
    );
    const permissions: string[] = user.userRoles.flatMap((item: any) =>
      item.role.rolePermissions.map((rolePermission: any) =>
        String(rolePermission.permission.code),
      ),
    );
    return {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      roles: [...new Set(roles.map(String))],
      teamIds: user.teamMemberships.map((item: any) => String(item.teamId)),
      permissions: [...new Set(permissions.map(String))],
    };
  }

  private jwtSecret() {
    const secret = this.config.get<string>("JWT_SECRET");
    if (!secret)
      throw new AppError(
        "SYSTEM_CONFIGURATION_MISSING",
        "JWT_SECRET 未配置",
        500,
      );
    return secret;
  }
}
