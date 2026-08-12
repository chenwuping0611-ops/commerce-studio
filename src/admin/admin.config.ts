import type { PrismaService } from "../common/database/prisma.service";

export function buildAdminOptions(
  prisma: PrismaService,
  getModelByName: (name: string) => unknown,
): Record<string, unknown> {
  return {
    rootPath: "/admin",
    locale: {
      language: "zh-CN",
      availableLanguages: ["zh-CN", "en"],
      translations: {
        "zh-CN": {
          labels: {
            navigation: "导航",
            User: "用户",
            Role: "角色",
            Permission: "权限",
            Team: "团队",
            Product: "产品",
            ProductVariant: "SKU 变体",
            ProductAsset: "产品素材",
            ModelProvider: "模型供应商",
            ModelProfile: "模型配置",
            GenerationTask: "生成任务",
            AuditLog: "审计日志",
            SystemSetting: "系统设置",
          },
        },
      },
    },
    branding: {
      companyName: "Commerce Studio",
      withMadeWithLove: false,
      logo: false,
    },
    dashboard: {
      component: undefined,
    },
    resources: [
      resource(prisma, getModelByName, "User", {
        navigation: "系统管理",
        properties: { passwordHash: { isVisible: false } },
      }),
      resource(prisma, getModelByName, "Role", { navigation: "权限管理" }),
      resource(prisma, getModelByName, "Permission", {
        navigation: "权限管理",
      }),
      resource(prisma, getModelByName, "Team", { navigation: "组织管理" }),
      resource(prisma, getModelByName, "Product", { navigation: "产品管理" }),
      resource(prisma, getModelByName, "ProductVariant", {
        navigation: "产品管理",
      }),
      resource(prisma, getModelByName, "ProductAsset", {
        navigation: "产品管理",
      }),
      resource(prisma, getModelByName, "ModelProvider", {
        navigation: "模型配置",
        properties: { apiKeyEncrypted: { isVisible: false } },
      }),
      resource(prisma, getModelByName, "ModelProfile", {
        navigation: "模型配置",
      }),
      resource(prisma, getModelByName, "GenerationTask", {
        navigation: "生成记录",
      }),
      resource(prisma, getModelByName, "AuditLog", { navigation: "系统管理" }),
      resource(prisma, getModelByName, "SystemSetting", {
        navigation: "系统管理",
      }),
    ],
    assets: {
      styles: "/workbench/assets/admin-overrides.css",
    },
  };
}

function resource(
  prisma: PrismaService,
  getModelByName: (name: string) => unknown,
  modelName: string,
  options: Record<string, unknown>,
) {
  return {
    resource: {
      model: getModelByName(modelName),
      client: prisma,
    },
    options,
  };
}
