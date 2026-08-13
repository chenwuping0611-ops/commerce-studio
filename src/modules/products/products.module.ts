import { Module } from "@nestjs/common";

import { AuditModule } from "../../common/audit/audit.module";
import { MediaModule } from "../../common/media/media.module";
import { AuthModule } from "../auth/auth.module";
import { RbacModule } from "../rbac/rbac.module";
import { ProductsController } from "./products.controller";
import { ProductsRepository } from "./products.repository";
import { ProductsService } from "./products.service";

@Module({
  imports: [AuditModule, AuthModule, MediaModule, RbacModule],
  controllers: [ProductsController],
  providers: [ProductsRepository, ProductsService],
  exports: [ProductsService, ProductsRepository],
})
export class ProductsModule {}
