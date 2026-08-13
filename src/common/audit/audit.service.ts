import { Injectable } from "@nestjs/common";
import { Prisma } from "@prisma/client";

import { PrismaService } from "../database/prisma.service";

@Injectable()
export class AuditService {
  constructor(private readonly prisma: PrismaService) {}

  /**
   * 目的：记录后台和业务写操作，便于定位问题和追踪责任。
   * 输入：操作者、动作、资源、资源 ID 和可脱敏元数据。
   * 输出：已持久化的审计记录。
   * 安全边界：调用方不得传入密码、Cookie、API Key 或完整授权头。
   * 幂等性：审计记录允许同一业务动作出现多条，不参与业务状态判断。
   */
  record(input: {
    actorId?: string;
    action: string;
    resource: string;
    resourceId?: string;
    requestId?: string;
    metadata?: Record<string, unknown>;
  }) {
    return this.prisma.auditLog.create({
      data: {
        actorId: input.actorId,
        action: input.action,
        resource: input.resource,
        resourceId: input.resourceId,
        requestId: input.requestId,
        metadata:
          input.metadata === undefined
            ? undefined
            : (JSON.parse(
                JSON.stringify(input.metadata),
              ) as Prisma.InputJsonValue),
      },
    });
  }
}
