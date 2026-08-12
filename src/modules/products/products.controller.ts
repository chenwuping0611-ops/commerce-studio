import {
  Body,
  BadRequestException,
  Controller,
  Get,
  Param,
  Post,
  Query,
  Patch,
  UseGuards,
} from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { CreateProductDto } from "./dto/create-product.dto";
import { CreateVariantDto } from "./dto/create-variant.dto";
import { UpdateProductDto } from "./dto/update-product.dto";
import { ProductsService } from "./products.service";

@ApiTags("products")
@Controller("products")
@UseGuards(AuthGuard, RbacGuard)
export class ProductsController {
  constructor(private readonly service: ProductsService) {}

  @Get()
  @RequirePermission("product:read:team")
  list(
    @CurrentUser() user: AuthenticatedUser,
    @Query("take") takeText?: string,
    @Query("cursor") cursor?: string,
  ) {
    return this.service.list(user, this.parseTake(takeText), cursor);
  }

  @Get(":id")
  @RequirePermission("product:read:team")
  getById(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.getById(user, id);
  }

  @Post()
  @RequirePermission("product:update:team")
  create(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CreateProductDto,
  ) {
    return this.service.create(user, dto);
  }

  @Patch(":id")
  @RequirePermission("product:update:team")
  update(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateProductDto,
  ) {
    return this.service.update(user, id, dto);
  }

  @Post(":id/variants")
  @RequirePermission("product:update:team")
  createVariant(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") productId: string,
    @Body() dto: CreateVariantDto,
  ) {
    return this.service.createVariant(user, productId, dto);
  }

  private parseTake(value?: string) {
    if (value === undefined || value.trim() === "") return undefined;
    const take = Number(value);
    if (!Number.isInteger(take) || take < 1) {
      throw new BadRequestException("take 必须是大于 0 的整数");
    }
    return take;
  }
}
