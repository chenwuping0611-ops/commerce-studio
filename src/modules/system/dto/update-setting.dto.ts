import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsBoolean, IsDefined, IsOptional } from "class-validator";

export class UpdateSettingDto {
  @ApiProperty()
  @IsDefined()
  value!: unknown;

  @ApiPropertyOptional()
  @IsOptional()
  @IsBoolean()
  isSecret?: boolean;
}
