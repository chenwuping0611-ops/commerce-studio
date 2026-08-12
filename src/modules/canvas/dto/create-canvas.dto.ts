import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsArray,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from "class-validator";

export class CreateCanvasDto {
  @ApiProperty({ example: "汽车广告视频方案" })
  @IsString()
  @MinLength(1)
  @MaxLength(160)
  name!: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  productId?: string;

  @ApiPropertyOptional({ type: [Object] })
  @IsOptional()
  @IsArray()
  nodes?: Array<Record<string, unknown>>;

  @ApiPropertyOptional({ type: [Object] })
  @IsOptional()
  @IsArray()
  edges?: Array<Record<string, unknown>>;

  @ApiPropertyOptional({ type: Object })
  @IsOptional()
  @IsObject()
  viewport?: Record<string, unknown>;

  @ApiPropertyOptional({ type: Object })
  @IsOptional()
  @IsObject()
  settings?: Record<string, unknown>;
}
