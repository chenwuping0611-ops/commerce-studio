import { randomUUID } from "node:crypto";
import type { NextFunction, Request, Response } from "express";

export class RequestIdMiddleware {
  use(request: Request, response: Response, next: NextFunction) {
    const requestId = request.header("x-request-id")?.trim() || randomUUID();
    request.requestId = requestId;
    response.setHeader("x-request-id", requestId);
    next();
  }
}
