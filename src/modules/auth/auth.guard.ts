import { CanActivate, ExecutionContext, Injectable } from "@nestjs/common";
import type { Request } from "express";

import { AppError } from "../../common/errors/app-error";
import { AuthService } from "./auth.service";

@Injectable()
export class AuthGuard implements CanActivate {
  constructor(private readonly authService: AuthService) {}

  async canActivate(context: ExecutionContext) {
    const request = context.switchToHttp().getRequest<Request>();
    const token = request.cookies?.access_token ?? this.bearerToken(request);
    if (!token) throw new AppError("AUTH_REQUIRED", "请先登录", 401);
    request.user = await this.authService.authenticateToken(token);
    return true;
  }

  private bearerToken(request: Request) {
    const header = request.header("authorization");
    if (!header?.startsWith("Bearer ")) return undefined;
    return header.slice("Bearer ".length).trim();
  }
}
