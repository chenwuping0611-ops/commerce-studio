import { TaskStatus } from "@prisma/client";

import { AppError } from "../../common/errors/app-error";
import {
  canTransitionTaskState,
  transitionTaskState,
} from "./generation-state";

describe("generation state machine", () => {
  it("allows the normal queued-to-success path", () => {
    expect(canTransitionTaskState(TaskStatus.CREATED, TaskStatus.QUEUED)).toBe(
      true,
    );
    expect(
      canTransitionTaskState(TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
    ).toBe(true);
    expect(
      transitionTaskState(TaskStatus.PROVIDER_PROCESSING, TaskStatus.SUCCEEDED),
    ).toBe(TaskStatus.SUCCEEDED);
  });

  it("rejects terminal state mutations", () => {
    expect(
      canTransitionTaskState(TaskStatus.SUCCEEDED, TaskStatus.QUEUED),
    ).toBe(false);
    expect(() =>
      transitionTaskState(TaskStatus.CANCELLED, TaskStatus.RUNNING),
    ).toThrow(AppError);
    try {
      transitionTaskState(TaskStatus.CANCELLED, TaskStatus.RUNNING);
    } catch (error) {
      expect(error).toMatchObject({
        code: "GENERATION_INVALID_STATE_TRANSITION",
      });
    }
  });
});
