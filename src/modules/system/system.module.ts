import { Module } from "@nestjs/common";

import { AuditModule } from "../../common/audit/audit.module";
import { AuthModule } from "../auth/auth.module";
import { RbacModule } from "../rbac/rbac.module";
import { SystemController } from "./system.controller";
import { SystemService } from "./system.service";

@Module({
  imports: [AuditModule, AuthModule, RbacModule],
  controllers: [SystemController],
  providers: [SystemService],
  exports: [SystemService],
})
export class SystemModule {}
