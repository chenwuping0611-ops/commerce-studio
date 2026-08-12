import { Module } from "@nestjs/common";

import { PrismaModule } from "../common/database/prisma.module";
import { PrismaService } from "../common/database/prisma.service";
import { AuthModule } from "../modules/auth/auth.module";
import { AdminBootstrapService } from "./admin.bootstrap";

@Module({
  imports: [PrismaModule, AuthModule],
  providers: [AdminBootstrapService],
  exports: [AdminBootstrapService],
})
export class AdminModule {}
