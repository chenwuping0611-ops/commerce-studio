import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

const permissionSeeds = [
  ["product:read:team", "查看团队产品"],
  ["product:update:team", "编辑团队产品"],
  ["memory:update:team", "编辑产品记忆"],
  ["generation:create:team", "创建生成任务"],
  ["generation:cancel:own", "取消自己的生成任务"],
  ["generation:read:team", "查看团队生成任务"],
  ["canvas:manage:team", "管理团队 Canvas"],
  ["model_config:read:system", "查看模型配置"],
  ["model_config:update:system", "修改模型配置"],
  ["user:manage:system", "管理用户"],
  ["audit:read:system", "查看审计日志"],
];

async function main() {
  const permissions = new Map<string, { id: string }>();
  for (const [code, name] of permissionSeeds) {
    const permission = await prisma.permission.upsert({
      where: { code },
      update: { name },
      create: { code, name },
    });
    permissions.set(code, permission);
  }

  const roles = {
    superAdmin: await prisma.role.upsert({
      where: { code: "super_admin" },
      update: { name: "超级管理员" },
      create: { code: "super_admin", name: "超级管理员" },
    }),
    teamLead: await prisma.role.upsert({
      where: { code: "team_lead" },
      update: { name: "团队负责人" },
      create: { code: "team_lead", name: "团队负责人" },
    }),
    employee: await prisma.role.upsert({
      where: { code: "employee" },
      update: { name: "员工" },
      create: { code: "employee", name: "员工" },
    }),
    visitor: await prisma.role.upsert({
      where: { code: "visitor" },
      update: { name: "访客" },
      create: { code: "visitor", name: "访客" },
    }),
  };

  const superAdminCodes = permissionSeeds.map(([code]) => code);
  const teamLeadCodes = [
    "product:read:team",
    "product:update:team",
    "memory:update:team",
    "generation:create:team",
    "generation:cancel:own",
    "generation:read:team",
    "canvas:manage:team",
  ];
  const employeeCodes = [
    "product:read:team",
    "generation:create:team",
    "generation:cancel:own",
    "generation:read:team",
    "canvas:manage:team",
  ];

  for (const [role, codes] of [
    [roles.superAdmin, superAdminCodes],
    [roles.teamLead, teamLeadCodes],
    [roles.employee, employeeCodes],
  ] as const) {
    for (const code of codes) {
      const permission = permissions.get(code);
      if (!permission) continue;
      await prisma.rolePermission.upsert({
        where: {
          roleId_permissionId: {
            roleId: role.id,
            permissionId: permission.id,
          },
        },
        update: {},
        create: { roleId: role.id, permissionId: permission.id },
      });
    }
  }

  const team = await prisma.team.upsert({
    where: { code: "default" },
    update: { name: "默认团队" },
    create: { code: "default", name: "默认团队" },
  });

  const adminEmail = process.env.ADMIN_EMAIL ?? "admin@example.com";
  const adminPassword = process.env.ADMIN_PASSWORD ?? "change-me";
  const admin = await prisma.user.upsert({
    where: { email: adminEmail },
    update: { displayName: "系统管理员", status: "ACTIVE" },
    create: {
      email: adminEmail,
      displayName: "系统管理员",
      passwordHash: await bcrypt.hash(adminPassword, 12),
    },
  });

  await prisma.userRole.upsert({
    where: {
      userId_roleId: {
        userId: admin.id,
        roleId: roles.superAdmin.id,
      },
    },
    update: {},
    create: { userId: admin.id, roleId: roles.superAdmin.id },
  });

  await prisma.teamMember.upsert({
    where: {
      userId_teamId: {
        userId: admin.id,
        teamId: team.id,
      },
    },
    update: { isLead: true },
    create: { userId: admin.id, teamId: team.id, isLead: true },
  });

  console.log(
    `Seeded admin user ${admin.email} and default team ${team.code}.`,
  );
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
