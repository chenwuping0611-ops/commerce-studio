import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import type { INestApplication } from "@nestjs/common";

import { PrismaService } from "../common/database/prisma.service";
import { AuthService } from "../modules/auth/auth.service";
import { buildAdminOptions } from "./admin.config";

type NativeImport = (specifier: string) => Promise<Record<string, any>>;

@Injectable()
export class AdminBootstrapService {
  private readonly logger = new Logger(AdminBootstrapService.name);
  private registered = false;

  constructor(
    private readonly prisma: PrismaService,
    private readonly auth: AuthService,
    private readonly config: ConfigService,
  ) {}

  /**
   * 目的：在 CommonJS Nest 应用中挂载 AdminJS 7 的 ESM 管理后台。
   * 输入：已创建但尚未启动监听的 Nest 应用。
   * 输出：挂载 `/admin` 路由的应用。
   * 外部副作用：动态加载 AdminJS、注册 Prisma 适配器并挂载 Express Router。
   * 安全边界：后台登录仍由 AuthService 校验，API Key 字段在资源配置中隐藏。
   * 幂等性：同一个应用实例只注册一次。
   */
  async register(app: INestApplication) {
    if (this.registered) return;

    const nativeImport = this.nativeImport();
    const [adminJsModule, adminExpressModule, prismaAdapterModule] =
      await Promise.all([
        nativeImport("adminjs"),
        nativeImport("@adminjs/express"),
        nativeImport("@adminjs/prisma"),
      ]);

    const AdminJS = adminJsModule.default;
    const AdminJSExpress = adminExpressModule.default;
    const { Database, Resource, getModelByName } = prismaAdapterModule;

    AdminJS.registerAdapter({ Database, Resource });
    const admin = new AdminJS(
      buildAdminOptions(this.prisma, (name) => getModelByName(name)),
    );
    if (this.config.get<boolean>("ADMINJS_WATCH", false)) {
      admin.watch();
    }

    const cookiePassword = this.config.get<string>(
      "ADMIN_COOKIE_PASSWORD",
      "replace-with-another-long-random-secret",
    );
    const router = AdminJSExpress.buildAuthenticatedRouter(
      admin,
      {
        authenticate: async (email: string, password: string) => {
          try {
            const user = await this.auth.validateCredentials(email, password);
            return user.roles.includes("super_admin") ? user : null;
          } catch {
            return null;
          }
        },
        cookieName: "commerce_studio_admin",
        cookiePassword,
      },
      undefined,
      {
        resave: false,
        saveUninitialized: false,
        secret: cookiePassword,
      },
    );

    app.getHttpAdapter().getInstance().use("/admin", router);
    this.registered = true;
    this.logger.log("AdminJS mounted at /admin.");
  }

  private nativeImport(): NativeImport {
    // TypeScript CommonJS output rewrites ordinary dynamic imports to require().
    // The native importer keeps AdminJS 7 ESM loading compatible with the Nest app.
    return new Function(
      "specifier",
      "return import(specifier)",
    ) as NativeImport;
  }
}
