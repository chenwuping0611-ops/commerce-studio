import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsArray,
  IsEmail,
  IsEnum,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from "class-validator";
import { UserStatus } from "@prisma/client";

export class CreateUserDto {
  @ApiProperty({ example: "operator@example.com" })
  @IsEmail()
  email!: string;

  @ApiProperty({ example: "change-this-password" })
  @IsString()
  @MinLength(8)
  @MaxLength(120)
  password!: string;

  @ApiProperty({ example: "内容运营" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  displayName!: string;

  @ApiPropertyOptional({ enum: UserStatus, default: UserStatus.ACTIVE })
  @IsOptional()
  @IsEnum(UserStatus)
  status?: UserStatus;

  @ApiPropertyOptional({ type: [String] })
  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  roleIds?: string[];

  @ApiPropertyOptional({ type: [String] })
  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  teamIds?: string[];
}
