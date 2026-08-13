import { ApiProperty } from "@nestjs/swagger";
import { IsString, MaxLength, MinLength } from "class-validator";

export class ResetPasswordDto {
  @ApiProperty({ example: "new-strong-password" })
  @IsString()
  @MinLength(8)
  @MaxLength(120)
  password!: string;
}
