import { Module } from "@nestjs/common";

import { AuthModule } from "../auth/auth.module";
import { ProductMemoryModule } from "../product-memory/product-memory.module";
import { RbacModule } from "../rbac/rbac.module";
import { SkillsModule } from "../skills/skills.module";
import { PromptEngineService } from "./prompt-engine.service";
import { PromptsController } from "./prompts.controller";

@Module({
  imports: [AuthModule, ProductMemoryModule, RbacModule, SkillsModule],
  controllers: [PromptsController],
  providers: [PromptEngineService],
  exports: [PromptEngineService],
})
export class PromptsModule {}
