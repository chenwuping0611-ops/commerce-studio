import {
  Body,
  Controller,
  Get,
  Param,
  Patch,
  Post,
  UseGuards,
} from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RequirePermission } from "../rbac/rbac.decorators";
import { RbacGuard } from "../rbac/rbac.guard";
import { CanvasService } from "./canvas.service";
import { CreateCanvasDto } from "./dto/create-canvas.dto";
import { UpdateCanvasDto } from "./dto/update-canvas.dto";

@ApiTags("canvas")
@Controller("canvas")
@UseGuards(AuthGuard, RbacGuard)
export class CanvasController {
  constructor(private readonly service: CanvasService) {}

  @Get()
  @RequirePermission("canvas:manage:team")
  list(@CurrentUser() user: AuthenticatedUser) {
    return this.service.list(user);
  }

  @Post()
  @RequirePermission("canvas:manage:team")
  create(@CurrentUser() user: AuthenticatedUser, @Body() dto: CreateCanvasDto) {
    return this.service.create(user, dto);
  }

  @Get(":id")
  @RequirePermission("canvas:manage:team")
  get(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.get(user, id);
  }

  @Patch(":id")
  @RequirePermission("canvas:manage:team")
  update(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateCanvasDto,
  ) {
    return this.service.update(user, id, dto);
  }

  @Post(":id/execute")
  @RequirePermission("canvas:manage:team")
  execute(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.execute(user, id);
  }
}
