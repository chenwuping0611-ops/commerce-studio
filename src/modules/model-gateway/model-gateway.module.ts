import { Module } from "@nestjs/common";

import { AuthModule } from "../auth/auth.module";
import { RbacModule } from "../rbac/rbac.module";
import { OpenAiCompatibleAdapter } from "./adapters/openai-compatible.adapter";
import { ModelGatewayController } from "./model-gateway.controller";
import { ModelGatewayService } from "./model-gateway.service";

@Module({
  imports: [AuthModule, RbacModule],
  controllers: [ModelGatewayController],
  providers: [OpenAiCompatibleAdapter, ModelGatewayService],
  exports: [ModelGatewayService],
})
export class ModelGatewayModule {}
