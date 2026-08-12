import {
  Injectable,
  Logger,
  OnModuleDestroy,
  OnModuleInit,
} from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { PrismaClient } from "@prisma/client";

@Injectable()
export class PrismaService
  extends PrismaClient
  implements OnModuleInit, OnModuleDestroy
{
  private readonly logger = new Logger(PrismaService.name);

  constructor(private readonly config: ConfigService) {
    super({
      datasources: {
        db: {
          url:
            config.get<string>("DATABASE_URL") ??
            "mysql://commerce:change-me@127.0.0.1:3306/commerce_studio",
        },
      },
      log:
        config.get("NODE_ENV", "development") === "development"
          ? ["warn", "error"]
          : ["error"],
    });
  }

  async onModuleInit() {
    if (this.config.get<boolean>("DATABASE_REQUIRED", false)) {
      await this.$connect();
      this.logger.log("Connected to MySQL.");
    } else {
      this.logger.warn(
        "DATABASE_REQUIRED=false. MySQL connection is deferred until a database-backed use case is called.",
      );
    }
  }

  async onModuleDestroy() {
    await this.$disconnect();
  }

  async checkConnection() {
    await this.$queryRaw`SELECT 1`;
    return true;
  }
}
