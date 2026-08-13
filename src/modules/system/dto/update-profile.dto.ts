import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString, MaxLength, MinLength } from "class-validator";

export class UpdateProfileDto {
  @ApiPropertyOptional({ example: "我的新昵称" })
  @IsOptional()
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  displayName?: string;

  @ApiPropertyOptional({ example: "old-password" })
  @IsOptional()
  @IsString()
  @MaxLength(120)
  currentPassword?: string;

  @ApiPropertyOptional({ example: "new-password" })
  @IsOptional()
  @IsString()
  @MinLength(8)
  @MaxLength(120)
  newPassword?: string;
}
