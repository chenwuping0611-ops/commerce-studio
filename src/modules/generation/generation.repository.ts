import { Injectable } from "@nestjs/common";
import { TaskStatus } from "@prisma/client";

import { PrismaService } from "../../common/database/prisma.service";

@Injectable()
export class GenerationRepository {
  constructor(private readonly prisma: PrismaService) {}

  findById(id: string) {
    return this.prisma.generationTask.findUnique({
      where: { id },
      include: {
        product: true,
        variant: true,
        provider: true,
        modelProfile: true,
        assets: true,
        attempts: { orderBy: { attempt: "desc" } },
      },
    });
  }

  findByIdempotencyKey(createdById: string, idempotencyKey: string) {
    return this.prisma.generationTask.findFirst({
      where: { createdById, idempotencyKey },
    });
  }

  list(where: Record<string, unknown>, take: number, cursor?: string) {
    return this.prisma.generationTask.findMany({
      where,
      take: take + 1,
      ...(cursor ? { skip: 1, cursor: { id: cursor } } : {}),
      orderBy: { createdAt: "desc" },
      include: {
        product: { select: { id: true, name: true, code: true } },
        modelProfile: { select: { id: true, name: true } },
        provider: { select: { id: true, name: true } },
        assets: true,
      },
    });
  }

  create(data: Record<string, unknown>) {
    return this.prisma.generationTask.create({
      data: data as never,
      include: { product: true, modelProfile: true, provider: true },
    });
  }

  update(id: string, data: Record<string, unknown>) {
    return this.prisma.generationTask.update({
      where: { id },
      data: data as never,
      include: {
        product: true,
        modelProfile: true,
        provider: true,
        assets: true,
      },
    });
  }

  async claimNext(now: Date, leaseUntil: Date) {
    const task = await this.prisma.generationTask.findFirst({
      where: {
        status: {
          in: [
            TaskStatus.QUEUED,
            TaskStatus.RETRY_WAITING,
            TaskStatus.PROVIDER_SUBMITTED,
            TaskStatus.PROVIDER_PROCESSING,
            TaskStatus.CANCEL_REQUESTED,
          ],
        },
        OR: [{ nextPollAt: null }, { nextPollAt: { lte: now } }],
      },
      orderBy: { createdAt: "asc" },
      include: { product: true, provider: true, modelProfile: true },
    });
    if (!task) return null;

    const claimData = {
      ...(task.status === TaskStatus.QUEUED ||
      task.status === TaskStatus.RETRY_WAITING
        ? { status: TaskStatus.RUNNING }
        : {}),
      leaseUntil,
      heartbeatAt: now,
    };
    const claimed = await this.prisma.generationTask.updateMany({
      where: {
        id: task.id,
        status: task.status,
        OR: [{ leaseUntil: null }, { leaseUntil: { lt: now } }],
      },
      data: claimData,
    });
    return claimed.count === 1
      ? { task: await this.findById(task.id), claimedFrom: task.status }
      : null;
  }

  findForWorker(id: string) {
    return this.prisma.generationTask.findUnique({
      where: { id },
      include: {
        product: true,
        provider: true,
        modelProfile: { include: { provider: true } },
      },
    });
  }

  createAttempt(data: Record<string, unknown>) {
    return this.prisma.generationAttempt.create({ data: data as never });
  }

  updateAttempt(id: string, data: Record<string, unknown>) {
    return this.prisma.generationAttempt.update({
      where: { id },
      data: data as never,
    });
  }

  createAsset(data: Record<string, unknown>) {
    return this.prisma.generationAsset.create({ data: data as never });
  }

  findAssetByTaskAndSha256(taskId: string, sha256: string) {
    return this.prisma.generationAsset.findFirst({
      where: { taskId, sha256 },
    });
  }

  deleteAssets(ids: string[]) {
    if (ids.length === 0) return Promise.resolve({ count: 0 });
    return this.prisma.generationAsset.deleteMany({
      where: { id: { in: ids } },
    });
  }
}
