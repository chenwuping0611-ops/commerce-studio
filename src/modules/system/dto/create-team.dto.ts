import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsOptional, IsString, MaxLength, MinLength } from "class-validator";

export class CreateTeamDto {
  @ApiProperty({ example: "内容团队" })
  @IsString()
  @MinLength(1)
  @MaxLength(120)
  name!: string;

  @ApiProperty({ example: "content-team" })
  @IsString()
  @MinLength(1)
  @MaxLength(80)
  code!: string;

  @ApiPropertyOptional({ example: "负责电商视觉内容生产" })
  @IsOptional()
  @IsString()
  @MaxLength(500)
  description?: string;
}
