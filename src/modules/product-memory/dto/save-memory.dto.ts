import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsArray, IsOptional, IsString, MaxLength } from "class-validator";

export class SaveMemoryDto {
  @ApiProperty({
    type: [Object],
    example: [{ key: "material", value: "铝合金" }],
  })
  @IsArray()
  facts!: Array<{ key: string; value: string; source?: string }>;

  @ApiProperty({
    type: [Object],
    example: [{ key: "tone", value: "高级、克制" }],
  })
  @IsArray()
  brandVisual!: Array<{ key: string; value: string }>;

  @ApiProperty({ type: [String], example: ["保持产品主体结构不变"] })
  @IsArray()
  @IsString({ each: true })
  generationRules!: string[];

  @ApiProperty({ type: [String], example: ["禁止出现其他品牌 Logo"] })
  @IsArray()
  @IsString({ each: true })
  forbiddenRules!: string[];

  @ApiPropertyOptional({ example: "补充当前季度的视觉方向" })
  @IsOptional()
  @IsString()
  @MaxLength(4000)
  notes?: string;
}
