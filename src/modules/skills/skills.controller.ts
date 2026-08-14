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

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { CreateSkillDto } from "./dto/create-skill.dto";
import { UpdateSkillDto } from "./dto/update-skill.dto";
import { SkillsService } from "./skills.service";

@ApiTags("skills")
@Controller("skills")
@UseGuards(AuthGuard, RbacGuard)
export class SkillsController {
  constructor(private readonly service: SkillsService) {}

  @Get()
  list(
    @CurrentUser() user: AuthenticatedUser,
    @Query("type") type?: "IMAGE" | "VIDEO",
  ) {
    return this.service.list(user, type);
  }

  @Get("admin")
  listForAdmin(@CurrentUser() user: AuthenticatedUser) {
    return this.service.listForAdmin(user);
  }

  @Post()
  create(@CurrentUser() user: AuthenticatedUser, @Body() dto: CreateSkillDto) {
    return this.service.create(user, dto);
  }

  @Patch(":id")
  update(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") id: string,
    @Body() dto: UpdateSkillDto,
  ) {
    return this.service.update(user, id, dto);
  }

  @Delete(":id")
  disable(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.disable(user, id);
  }
}
