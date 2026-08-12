import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsIn,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from "class-validator";

export class CompilePromptDto {
  @ApiProperty({ example: "生成一个高级汽车广告视频" })
  @IsString()
  @MinLength(1)
  @MaxLength(4000)
  idea!: string;

  @ApiPropertyOptional({ enum: ["IMAGE", "VIDEO"], default: "IMAGE" })
  @IsOptional()
  @IsIn(["IMAGE", "VIDEO"])
  type?: "IMAGE" | "VIDEO";

  @ApiPropertyOptional({ example: "16:9" })
  @IsOptional()
  @IsString()
  @MaxLength(20)
  aspectRatio?: string;
}
