import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsBoolean,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from "class-validator";

export class CreateModelProfileDto {
  @ApiProperty({ example: "image-model-v1" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  name!: string;

  @ApiProperty({ example: { image: true, video: false } })
  @IsObject()
  capability!: Record<string, unknown>;

  @ApiPropertyOptional({ example: "/images/generations" })
  @IsOptional()
  @IsString()
  @MaxLength(200)
  endpointPath?: string;

  @ApiPropertyOptional({ default: true })
  @IsOptional()
  @IsBoolean()
  enabled?: boolean;
}
