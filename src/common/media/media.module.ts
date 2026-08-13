import { Global, Module } from "@nestjs/common";

import { PrismaModule } from "../database/prisma.module";
import { MediaController } from "./media.controller";
import { MediaService } from "./media.service";

@Global()
@Module({
  imports: [PrismaModule],
  controllers: [MediaController],
  providers: [MediaService],
  exports: [MediaService],
})
export class MediaModule {}
