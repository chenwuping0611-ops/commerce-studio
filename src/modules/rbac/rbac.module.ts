import { Module } from "@nestjs/common";

import { RbacGuard } from "./rbac.guard";
import { RbacService } from "./rbac.service";

@Module({
  providers: [RbacService, RbacGuard],
  exports: [RbacService, RbacGuard],
})
export class RbacModule {}
