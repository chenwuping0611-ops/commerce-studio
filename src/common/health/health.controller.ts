import { Controller, Get, HttpCode, HttpStatus } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";

import { PrismaService } from "../database/prisma.service";

@Controller("health")
export class HealthController {
  constructor(
    private readonly prisma: PrismaService,
    private readonly config: ConfigService,
  ) {}

  @Get("live")
  @HttpCode(HttpStatus.OK)
  live() {
    return {
      data: {
        status: "ok",
        service: this.config.get("APP_NAME", "commerce-studio"),
        timestamp: new Date().toISOString(),
      },
    };
  }

  @Get("ready")
  async ready() {
    try {
      await this.prisma.checkConnection();
      return {
        data: {
          status: "ready",
          database: "ok",
          timestamp: new Date().toISOString(),
        },
      };
    } catch {
      return {
        data: {
          status: "degraded",
          database: "unavailable",
          hint: "Configure DATABASE_URL and start the external MySQL service.",
          timestamp: new Date().toISOString(),
        },
      };
    }
  }
}
