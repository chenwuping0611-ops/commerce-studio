import { ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString, MaxLength } from "class-validator";

export class CreateProductAssetDto {
  @ApiPropertyOptional({ example: "PRODUCT_REFERENCE" })
  @IsOptional()
  @IsString()
  @MaxLength(60)
  type?: string;

  @ApiPropertyOptional({ example: "front" })
  @IsOptional()
  @IsString()
  @MaxLength(60)
  view?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  variantId?: string;
}
