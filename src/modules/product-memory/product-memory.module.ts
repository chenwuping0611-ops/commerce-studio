import { Module } from "@nestjs/common";

import { AuthModule } from "../auth/auth.module";
import { ProductsModule } from "../products/products.module";
import { RbacModule } from "../rbac/rbac.module";
import { ProductMemoryController } from "./product-memory.controller";
import { ProductMemoryService } from "./product-memory.service";

@Module({
  imports: [AuthModule, ProductsModule, RbacModule],
  controllers: [ProductMemoryController],
  providers: [ProductMemoryService],
  exports: [ProductMemoryService],
})
export class ProductMemoryModule {}
