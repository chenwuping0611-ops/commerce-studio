import { Body, Controller, Get, Param, Put, UseGuards } from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { SaveMemoryDto } from "./dto/save-memory.dto";
import { ProductMemoryService } from "./product-memory.service";

@ApiTags("product-memory")
@Controller("products/:productId/memory")
@UseGuards(AuthGuard, RbacGuard)
export class ProductMemoryController {
  constructor(private readonly service: ProductMemoryService) {}

  @Get()
  @RequirePermission("product:read:team")
  get(
    @CurrentUser() user: AuthenticatedUser,
    @Param("productId") productId: string,
  ) {
    return this.service.get(user, productId);
  }

  @Put()
  @RequirePermission("memory:update:team")
  save(
    @CurrentUser() user: AuthenticatedUser,
    @Param("productId") productId: string,
    @Body() dto: SaveMemoryDto,
  ) {
    return this.service.save(user, productId, dto);
  }
}
