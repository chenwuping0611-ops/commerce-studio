import {
  Body,
  Controller,
  Get,
  Header,
  Headers,
  BadRequestException,
  Param,
  Post,
  Query,
  Res,
  Sse,
  UseGuards,
} from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";
import type { Response } from "express";

import { AuthGuard } from "../auth/auth.guard";
import { CurrentUser } from "../auth/current-user.decorator";
import type { AuthenticatedUser } from "../auth/auth.types";
import { RbacGuard } from "../rbac/rbac.guard";
import { RequirePermission } from "../rbac/rbac.decorators";
import { CreateGenerationTaskDto } from "./dto/create-generation-task.dto";
import { GenerationEventsService } from "./generation-events.service";
import { GenerationService } from "./generation.service";

@ApiTags("generation")
@Controller()
@UseGuards(AuthGuard, RbacGuard)
export class GenerationController {
  constructor(
    private readonly service: GenerationService,
    private readonly events: GenerationEventsService,
  ) {}

  @Post("generation-tasks")
  @RequirePermission("generation:create:team")
  create(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CreateGenerationTaskDto,
    @Headers("idempotency-key") headerIdempotencyKey?: string,
    @Query("idempotencyKey") queryIdempotencyKey?: string,
  ) {
    return this.service.create(
      user,
      dto,
      headerIdempotencyKey?.trim() || queryIdempotencyKey?.trim(),
    );
  }

  @Get("generation-tasks")
  @RequirePermission("generation:read:team")
  list(
    @CurrentUser() user: AuthenticatedUser,
    @Query("take") takeText?: string,
    @Query("cursor") cursor?: string,
  ) {
    return this.service.list(user, this.parseTake(takeText), cursor);
  }

  @Get("generation-tasks/:id")
  @RequirePermission("generation:read:team")
  get(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.get(user, id);
  }

  @Get("generation-tasks/:id/assets/:assetId/content")
  @RequirePermission("generation:read:team")
  @Header("Cache-Control", "private, max-age=3600")
  async assetContent(
    @CurrentUser() user: AuthenticatedUser,
    @Param("id") taskId: string,
    @Param("assetId") assetId: string,
    @Res() response: Response,
  ) {
    const asset = await this.service.getAssetForRead(user, taskId, assetId);
    response.setHeader("Content-Type", asset.mimeType);
    response.setHeader("Content-Length", asset.byteSize);
    response.setHeader(
      "Content-Disposition",
      `inline; filename="${asset.originalName ?? "generated-asset"}"`,
    );
    const stream = this.service.mediaStream(asset.storageKey);
    stream.on("error", () => response.destroy());
    stream.pipe(response);
  }

  @Post("generation-tasks/:id/cancel")
  @RequirePermission("generation:cancel:own")
  cancel(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.cancel(user, id);
  }

  @Post("generation-tasks/:id/retry")
  @RequirePermission("generation:create:team")
  retry(@CurrentUser() user: AuthenticatedUser, @Param("id") id: string) {
    return this.service.retry(user, id);
  }

  @Sse("events/generation/:taskId")
  @Header("Cache-Control", "no-cache")
  @Header("Connection", "keep-alive")
  @Header("X-Accel-Buffering", "no")
  async stream(
    @CurrentUser() user: AuthenticatedUser,
    @Param("taskId") taskId: string,
  ) {
    await this.service.get(user, taskId);
    return this.events.stream(taskId);
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
