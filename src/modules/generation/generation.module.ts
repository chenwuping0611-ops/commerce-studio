import { Module } from "@nestjs/common";

import { AuthModule } from "../auth/auth.module";
import { ModelGatewayModule } from "../model-gateway/model-gateway.module";
import { ProductMemoryModule } from "../product-memory/product-memory.module";
import { ProductsModule } from "../products/products.module";
import { PromptsModule } from "../prompts/prompts.module";
import { RbacModule } from "../rbac/rbac.module";
import { GenerationController } from "./generation.controller";
import { GenerationEventsService } from "./generation-events.service";
import { GenerationRepository } from "./generation.repository";
import { GenerationScheduler } from "./generation.scheduler";
import { GenerationService } from "./generation.service";
import { GenerationWorker } from "./generation.worker";

@Module({
  imports: [
    AuthModule,
    ModelGatewayModule,
    ProductMemoryModule,
    ProductsModule,
    PromptsModule,
    RbacModule,
  ],
  controllers: [GenerationController],
  providers: [
    GenerationEventsService,
    GenerationRepository,
    GenerationService,
    GenerationWorker,
    GenerationScheduler,
  ],
  exports: [GenerationEventsService, GenerationService],
})
export class GenerationModule {}
