import { Injectable } from "@nestjs/common";

import { AppError } from "../../common/errors/app-error";
import type { AuthenticatedUser } from "../auth/auth.types";

@Injectable()
export class RbacService {
  hasPermission(user: AuthenticatedUser, permission: string) {
    return (
      user.roles.includes("super_admin") ||
      user.permissions.includes(permission)
    );
  }

  assertPermission(user: AuthenticatedUser, permission: string) {
    if (!this.hasPermission(user, permission)) {
      throw new AppError(
        "RBAC_PERMISSION_DENIED",
        "没有执行此操作的权限",
        403,
        {
          permission,
        },
      );
    }
  }

  isSystemAdmin(user: AuthenticatedUser) {
    return user.roles.includes("super_admin");
  }

  accessibleTeamIds(user: AuthenticatedUser) {
    return this.isSystemAdmin(user) ? undefined : { in: user.teamIds };
  }
}
