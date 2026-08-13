import { ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsBoolean,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
} from "class-validator";

export class UpdateModelProfileDto {
  @ApiPropertyOptional({ example: "image-model-v1" })
  @IsOptional()
  @IsString()
  @MaxLength(120)
  name?: string;

  @ApiPropertyOptional({ type: Object })
  @IsOptional()
  @IsObject()
  capability?: Record<string, unknown>;

  @ApiPropertyOptional({ example: "/images/generations" })
  @IsOptional()
  @IsString()
  @MaxLength(240)
  endpointPath?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsBoolean()
  enabled?: boolean;
}
