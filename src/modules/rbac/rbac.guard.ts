import { CanActivate, ExecutionContext, Injectable } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import type { Request } from "express";

import { AppError } from "../../common/errors/app-error";
import { REQUIRED_PERMISSION_KEY } from "./rbac.decorators";
import { RbacService } from "./rbac.service";

@Injectable()
export class RbacGuard implements CanActivate {
  constructor(
    private readonly reflector: Reflector,
    private readonly rbacService: RbacService,
  ) {}

  canActivate(context: ExecutionContext) {
    const permission = this.reflector.getAllAndOverride<string>(
      REQUIRED_PERMISSION_KEY,
      [context.getHandler(), context.getClass()],
    );
    if (!permission) return true;
    const request = context.switchToHttp().getRequest<Request>();
    if (!request.user) throw new AppError("AUTH_REQUIRED", "请先登录", 401);
    if (!this.rbacService.hasPermission(request.user, permission)) {
      throw new AppError(
        "RBAC_PERMISSION_DENIED",
        "没有执行此操作的权限",
        403,
        {
          permission,
        },
      );
    }
    return true;
  }
}
