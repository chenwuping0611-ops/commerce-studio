import { Body, Controller, Get, Param, Post, UseGuards } from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { CreateProviderDto } from "./dto/create-provider.dto";
import { CreateModelProfileDto } from "./dto/create-model-profile.dto";
import { ModelGatewayService } from "./model-gateway.service";

@ApiTags("model-gateway")
@Controller("model-gateway")
@UseGuards(AuthGuard, RbacGuard)
export class ModelGatewayController {
  constructor(private readonly service: ModelGatewayService) {}

  @Get("providers")
  @RequirePermission("model_config:read:system")
  listProviders(@CurrentUser() user: AuthenticatedUser) {
    return this.service.listProviders(user);
  }

  @Post("providers")
  @RequirePermission("model_config:update:system")
  createProvider(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CreateProviderDto,
  ) {
    return this.service.createProvider(user, dto);
  }

  @Post("providers/:providerId/profiles")
  @RequirePermission("model_config:update:system")
  createProfile(
    @CurrentUser() user: AuthenticatedUser,
    @Param("providerId") providerId: string,
    @Body() dto: CreateModelProfileDto,
  ) {
    return this.service.createProfile(user, providerId, dto);
  }
}
