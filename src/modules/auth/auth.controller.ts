import { Body, Controller, Get, Post, Res, UseGuards } from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";
import { ConfigService } from "@nestjs/config";
import type { Response } from "express";

import { LoginDto } from "./dto/login.dto";
import { AuthService } from "./auth.service";
import { AuthGuard } from "./auth.guard";
import { CurrentUser } from "./current-user.decorator";
import type { AuthenticatedUser } from "./auth.types";

@ApiTags("auth")
@Controller("auth")
export class AuthController {
  constructor(
    private readonly authService: AuthService,
    private readonly config: ConfigService,
  ) {}

  @Post("login")
  async login(
    @Body() dto: LoginDto,
    @Res({ passthrough: true }) response: Response,
  ) {
    const user = await this.authService.validateCredentials(
      dto.email,
      dto.password,
    );
    response.cookie("access_token", this.authService.issueToken(user), {
      httpOnly: true,
      secure: this.config.get<boolean>("COOKIE_SECURE", false),
      sameSite: this.config.get<"lax" | "strict" | "none">(
        "COOKIE_SAME_SITE",
        "lax",
      ),
      maxAge: 8 * 60 * 60 * 1000,
      path: "/",
    });
    return { data: user };
  }

  @Post("logout")
  logout(@Res({ passthrough: true }) response: Response) {
    response.clearCookie("access_token", { httpOnly: true, path: "/" });
    return { data: { loggedOut: true } };
  }

  @Get("me")
  @UseGuards(AuthGuard)
  me(@CurrentUser() user: AuthenticatedUser) {
    return { data: user };
  }

  @Get("permissions")
  @UseGuards(AuthGuard)
  permissions(@CurrentUser() user: AuthenticatedUser) {
    return {
      data: {
        roles: user.roles,
        permissions: user.permissions,
        teamIds: user.teamIds,
      },
    };
  }
}
