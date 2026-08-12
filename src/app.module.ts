import { Module } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { ScheduleModule } from "@nestjs/schedule";

import { validateEnv } from "./common/config/env.validation";
import { PrismaModule } from "./common/database/prisma.module";
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

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      cache: true,
      validate: validateEnv,
    }),
    ScheduleModule.forRoot(),
    PrismaModule,
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
    AdminModule,
  ],
})
export class AppModule {}
