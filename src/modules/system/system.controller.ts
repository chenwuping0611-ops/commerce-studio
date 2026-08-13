import {
  Body,
  Controller,
  Get,
  Param,
  Patch,
  Post,
  Query,
  Req,
  UseGuards,
} from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";
import type { Request } from "express";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { AddTeamMemberDto } from "./dto/add-team-member.dto";
import { CreateTeamDto } from "./dto/create-team.dto";
import { CreateUserDto } from "./dto/create-user.dto";
import { ResetPasswordDto } from "./dto/reset-password.dto";
import { UpdateProfileDto } from "./dto/update-profile.dto";
import { UpdateRolePermissionsDto } from "./dto/update-role-permissions.dto";
import { UpdateSettingDto } from "./dto/update-setting.dto";
import { UpdateTeamDto } from "./dto/update-team.dto";
import { UpdateUserDto } from "./dto/update-user.dto";
import { SystemService } from "./system.service";

@ApiTags("system")
@Controller("system")
@UseGuards(AuthGuard, RbacGuard)
export class SystemController {
  constructor(private readonly service: SystemService) {}

  @Get("users")
  @RequirePermission("user:manage:system")
  listUsers(@CurrentUser() user: AuthenticatedUser) {
    return this.service.listUsers(user);
  }

  @Post("users")
  @RequirePermission("user:manage:system")
  createUser(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CreateUserDto,
    @Req() request: Request,
  ) {
    return this.service.createUser(user, dto, request.requestId);
  }

  @Patch("users/:id")
  @RequirePermission("user:manage:system")
  updateUser(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateUserDto,
    @Req() request: Request,
  ) {
    return this.service.updateUser(user, id, dto, request.requestId);
  }

  @Post("users/:id/reset-password")
  @RequirePermission("user:manage:system")
  resetPassword(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: ResetPasswordDto,
    @Req() request: Request,
  ) {
    return this.service.resetPassword(user, id, dto, request.requestId);
  }

  @Get("roles")
  @RequirePermission("user:manage:system")
  listRoles(@CurrentUser() user: AuthenticatedUser) {
    return this.service.listRoles(user);
  }

  @Patch("roles/:id/permissions")
  @RequirePermission("user:manage:system")
  updateRolePermissions(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateRolePermissionsDto,
    @Req() request: Request,
  ) {
    return this.service.updateRolePermissions(user, id, dto, request.requestId);
  }

  @Get("teams")
  @RequirePermission("user:manage:system")
  listTeams(@CurrentUser() user: AuthenticatedUser) {
    return this.service.listTeams(user);
  }

  @Post("teams")
  @RequirePermission("user:manage:system")
  createTeam(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CreateTeamDto,
    @Req() request: Request,
  ) {
    return this.service.createTeam(user, dto, request.requestId);
  }

  @Patch("teams/:id")
  @RequirePermission("user:manage:system")
  updateTeam(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateTeamDto,
    @Req() request: Request,
  ) {
    return this.service.updateTeam(user, id, dto, request.requestId);
  }

  @Post("teams/:id/members")
  @RequirePermission("user:manage:system")
  addTeamMember(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: AddTeamMemberDto,
    @Req() request: Request,
  ) {
    return this.service.addTeamMember(user, id, dto, request.requestId);
  }

  @Get("settings")
  @RequirePermission("model_config:read:system")
  listSettings(@CurrentUser() user: AuthenticatedUser) {
    return this.service.listSettings(user);
  }

  @Post("settings/:key")
  @RequirePermission("model_config:update:system")
  upsertSetting(
    @CurrentUser() user: AuthenticatedUser,
    @Param("key") key: string,
    @Body() dto: UpdateSettingDto,
    @Req() request: Request,
  ) {
    return this.service.upsertSetting(user, key, dto, request.requestId);
  }

  @Get("audit-logs")
  @RequirePermission("audit:read:system")
  listAuditLogs(
    @CurrentUser() user: AuthenticatedUser,
    @Query("take") takeText?: string,
  ) {
    const take = takeText ? Number(takeText) : 50;
    return this.service.listAuditLogs(user, Number.isFinite(take) ? take : 50);
  }

  @Patch("profile")
  updateProfile(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: UpdateProfileDto,
    @Req() request: Request,
  ) {
    return this.service.updateProfile(user, dto, request.requestId);
  }
}
