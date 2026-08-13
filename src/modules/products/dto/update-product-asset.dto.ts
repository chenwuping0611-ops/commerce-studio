import { ApiPropertyOptional } from "@nestjs/swagger";
import { IsEnum, IsOptional, IsString, MaxLength } from "class-validator";
import { AssetReviewStatus } from "@prisma/client";

export class UpdateProductAssetDto {
  @ApiPropertyOptional({ enum: AssetReviewStatus })
  @IsOptional()
  @IsEnum(AssetReviewStatus)
  reviewStatus?: AssetReviewStatus;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(60)
  view?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(60)
  type?: string;
}
