import { Module } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { ScheduleModule } from "@nestjs/schedule";

import { AuditModule } from "./common/audit/audit.module";
import { validateEnv } from "./common/config/env.validation";
import { PrismaModule } from "./common/database/prisma.module";
import { MediaModule } from "./common/media/media.module";
import { SecurityModule } from "./common/security/security.module";
import { HealthModule } from "./common/health/health.module";
import { AdminModule } from "./admin/admin.module";
import { AuthModule } from "./modules/auth/auth.module";
import { RbacModule } from "./modules/rbac/rbac.module";
import { ProductsModule } from "./modules/products/products.module";
import { ProductMemoryModule } from "./modules/product-memory/product-memory.module";
import { PromptsModule } from "./modules/prompts/prompts.module";
import { ModelGatewayModule } from "./modules/model-gateway/model-gateway.module";
import { GenerationModule } from "./modules/generation/generation.module";
import { CanvasModule } from "./modules/canvas/canvas.module";
import { SystemModule } from "./modules/system/system.module";

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      cache: true,
      validate: validateEnv,
    }),
    ScheduleModule.forRoot(),
    PrismaModule,
    AuditModule,
    MediaModule,
    SecurityModule,
    HealthModule,
    RbacModule,
    AuthModule,
    ProductsModule,
    ProductMemoryModule,
    PromptsModule,
    ModelGatewayModule,
    GenerationModule,
    CanvasModule,
    SystemModule,
    AdminModule,
  ],
})
export class AppModule {}
