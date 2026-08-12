import { TaskStatus } from "@prisma/client";

import { AppError } from "../../common/errors/app-error";

const transitions: Record<TaskStatus, TaskStatus[]> = {
  CREATED: ["QUEUED", "CANCELLED", "FAILED"],
  QUEUED: ["RUNNING", "CANCEL_REQUESTED", "CANCELLED", "EXPIRED"],
  RUNNING: [
    "PROVIDER_SUBMITTED",
    "SUCCEEDED",
    "FAILED",
    "RETRY_WAITING",
    "CANCEL_REQUESTED",
  ],
  PROVIDER_SUBMITTED: [
    "PROVIDER_PROCESSING",
    "SUCCEEDED",
    "FAILED",
    "RETRY_WAITING",
    "CANCEL_REQUESTED",
  ],
  PROVIDER_PROCESSING: [
    "SUCCEEDED",
    "FAILED",
    "RETRY_WAITING",
    "CANCEL_REQUESTED",
    "EXPIRED",
  ],
  SUCCEEDED: [],
  FAILED: ["RETRY_WAITING"],
  RETRY_WAITING: ["QUEUED", "CANCELLED", "EXPIRED"],
  CANCEL_REQUESTED: ["CANCELLED", "FAILED"],
  CANCELLED: [],
  EXPIRED: ["RETRY_WAITING", "CANCELLED"],
};

export function canTransitionTaskState(from: TaskStatus, to: TaskStatus) {
  return from === to || transitions[from].includes(to);
}

/**
 * 目的：集中校验生成任务状态转换，防止不同模块直接写入非法状态。
 * 输入：当前状态和目标状态。
 * 输出：目标状态；非法转换抛出稳定错误。
 * 外部副作用：无。
 */
export function transitionTaskState(from: TaskStatus, to: TaskStatus) {
  if (!canTransitionTaskState(from, to)) {
    throw new AppError(
      "GENERATION_INVALID_STATE_TRANSITION",
      `任务不能从 ${from} 转为 ${to}`,
      409,
      {
        from,
        to,
      },
    );
  }
  return to;
}
