import { Module } from "@nestjs/common";

import { AuthModule } from "../auth/auth.module";
import { ProductsModule } from "../products/products.module";
import { RbacModule } from "../rbac/rbac.module";
import { CanvasController } from "./canvas.controller";
import { CanvasService } from "./canvas.service";

@Module({
  imports: [AuthModule, ProductsModule, RbacModule],
  controllers: [CanvasController],
  providers: [CanvasService],
  exports: [CanvasService],
})
export class CanvasModule {}
