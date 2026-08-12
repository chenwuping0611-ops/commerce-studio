import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString, MaxLength, MinLength } from "class-validator";

export class CreateProductDto {
  @ApiProperty({ example: "高级无线耳机" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  name!: string;

  @ApiProperty({ example: "HEADPHONE-001" })
  @IsString()
  @MinLength(1)
  @MaxLength(80)
  code!: string;

  @ApiPropertyOptional({ example: "Example Audio" })
  @IsOptional()
  @IsString()
  @MaxLength(120)
  brand?: string;

  @ApiPropertyOptional({ example: "3C 数码" })
  @IsOptional()
  @IsString()
  @MaxLength(120)
  category?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(10000)
  description?: string;
}
