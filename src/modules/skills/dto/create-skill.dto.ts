import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsArray,
  IsBoolean,
  IsIn,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from "class-validator";

export class CreateSkillDto {
  @ApiProperty({ example: "高级电商主图" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  name!: string;

  @ApiProperty({ example: "commerce-product-hero" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  code!: string;

  @ApiProperty({ enum: ["IMAGE", "VIDEO", "BOTH"] })
  @IsIn(["IMAGE", "VIDEO", "BOTH"])
  mediaType!: "IMAGE" | "VIDEO" | "BOTH";

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(1000)
  description?: string;

  @ApiPropertyOptional({ example: "1.0.0" })
  @IsOptional()
  @IsString()
  @MaxLength(40)
  version?: string;

  @ApiPropertyOptional({ type: [String] })
  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  tags?: string[];

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(12000)
  promptTemplate?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(6000)
  negativePrompt?: string;

  @ApiPropertyOptional({ type: Object })
  @IsOptional()
  @IsObject()
  settings?: Record<string, unknown>;

  @ApiPropertyOptional({ default: true })
  @IsOptional()
  @IsBoolean()
  enabled?: boolean;
}
