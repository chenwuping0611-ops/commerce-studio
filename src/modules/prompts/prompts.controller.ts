import { Body, Controller, Param, Post, UseGuards } from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { CompilePromptDto } from "./dto/compile-prompt.dto";
import { PromptEngineService } from "./prompt-engine.service";

@ApiTags("prompts")
@Controller("products/:productId/prompt")
@UseGuards(AuthGuard, RbacGuard)
export class PromptsController {
  constructor(private readonly service: PromptEngineService) {}

  @Post("compile")
  @RequirePermission("generation:create:team")
  compile(
    @CurrentUser() user: AuthenticatedUser,
    @Param("productId") productId: string,
    @Body() dto: CompilePromptDto,
  ) {
    return this.service.compile(user, productId, dto);
  }
}
