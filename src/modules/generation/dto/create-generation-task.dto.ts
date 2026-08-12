import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsArray,
  IsIn,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from "class-validator";

export class CreateGenerationTaskDto {
  @ApiProperty()
  @IsString()
  @MinLength(1)
  productId!: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  variantId?: string;

  @ApiProperty()
  @IsString()
  @MinLength(1)
  modelProfileId!: string;

  @ApiProperty({ enum: ["IMAGE", "VIDEO"] })
  @IsIn(["IMAGE", "VIDEO"])
  type!: "IMAGE" | "VIDEO";

  @ApiProperty({ example: "生成一个高级汽车广告视频" })
  @IsString()
  @MinLength(1)
  @MaxLength(4000)
  idea!: string;

  @ApiPropertyOptional({ type: [String] })
  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  inputAssets?: string[];

  @ApiPropertyOptional({ type: Object })
  @IsOptional()
  @IsObject()
  options?: Record<string, unknown>;

  @ApiPropertyOptional({
    description: "重复提交保护键；也支持 Idempotency-Key 请求头。",
  })
  @IsOptional()
  @IsString()
  @MaxLength(200)
  idempotencyKey?: string;
}
