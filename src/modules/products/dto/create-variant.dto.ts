import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString, MaxLength, MinLength } from "class-validator";

export class CreateVariantDto {
  @ApiProperty({ example: "HEADPHONE-001-BLACK" })
  @IsString()
  @MinLength(1)
  @MaxLength(80)
  sku!: string;

  @ApiPropertyOptional({ example: "黑色标准版" })
  @IsOptional()
  @IsString()
  @MaxLength(120)
  name?: string;

  @ApiPropertyOptional({ example: "黑色" })
  @IsOptional()
  @IsString()
  @MaxLength(80)
  color?: string;

  @ApiPropertyOptional({ example: "标准" })
  @IsOptional()
  @IsString()
  @MaxLength(80)
  size?: string;

  @ApiPropertyOptional({ example: "铝合金" })
  @IsOptional()
  @IsString()
  @MaxLength(120)
  material?: string;
}
