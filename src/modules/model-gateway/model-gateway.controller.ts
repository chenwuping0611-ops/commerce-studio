import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  Patch,
  Post,
  Query,
  UseGuards,
} from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";
import { GenerationType } from "@prisma/client";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { CreateProviderDto } from "./dto/create-provider.dto";
import { CreateModelProfileDto } from "./dto/create-model-profile.dto";
import { UpdateModelProfileDto } from "./dto/update-model-profile.dto";
import { UpdateProviderDto } from "./dto/update-provider.dto";
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

  @Get("providers/:providerId/remote-models")
  @RequirePermission("model_config:read:system")
  listRemoteModels(
    @CurrentUser() user: AuthenticatedUser,
    @Param("providerId") providerId: string,
    @Query("type") type?: string,
  ) {
    return this.service.listRemoteModels(user, providerId, type);
  }

  @Get("providers/:providerId/balance")
  @RequirePermission("model_config:read:system")
  getProviderBalance(
    @CurrentUser() user: AuthenticatedUser,
    @Param("providerId") providerId: string,
  ) {
    return this.service.getProviderBalance(user, providerId);
  }

  @Get("profiles")
  @RequirePermission("generation:create:team")
  listAvailableProfiles(
    @CurrentUser() user: AuthenticatedUser,
    @Query("type") type?: string,
  ) {
    const generationType =
      type === "VIDEO"
        ? GenerationType.VIDEO
        : type === "IMAGE"
          ? GenerationType.IMAGE
          : undefined;
    return this.service.listAvailableProfiles(user, generationType);
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

  @Patch("providers/:providerId")
  @RequirePermission("model_config:update:system")
  updateProvider(
    @CurrentUser() user: AuthenticatedUser,
    @Param("providerId") providerId: string,
    @Body() dto: UpdateProviderDto,
  ) {
    return this.service.updateProvider(user, providerId, dto);
  }

  @Patch("profiles/:profileId")
  @RequirePermission("model_config:update:system")
  updateProfile(
    @CurrentUser() user: AuthenticatedUser,
    @Param("profileId") profileId: string,
    @Body() dto: UpdateModelProfileDto,
  ) {
    return this.service.updateProfile(user, profileId, dto);
  }

  @Delete("profiles/:profileId")
  @RequirePermission("model_config:update:system")
  deleteProfile(
    @CurrentUser() user: AuthenticatedUser,
    @Param("profileId") profileId: string,
  ) {
    return this.service.deleteProfile(user, profileId);
  }
}
