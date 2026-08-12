import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import {
  IsIn,
  IsOptional,
  IsString,
  IsUrl,
  MaxLength,
  MinLength,
} from "class-validator";

export class CreateProviderDto {
  @ApiProperty({ example: "官方图片服务" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  name!: string;

  @ApiProperty({ enum: ["NATIVE", "OPENAI_COMPATIBLE"] })
  @IsIn(["NATIVE", "OPENAI_COMPATIBLE"])
  kind!: "NATIVE" | "OPENAI_COMPATIBLE";

  @ApiProperty({ example: "https://api.example.com/v1" })
  @IsUrl({ require_protocol: true })
  baseUrl!: string;

  @ApiProperty()
  @IsString()
  @MinLength(8)
  apiKey!: string;

  @ApiPropertyOptional({ default: true })
  @IsOptional()
  enabled?: boolean;
}
