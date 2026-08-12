import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
  Logger,
} from "@nestjs/common";
import type { Request, Response } from "express";

import { AppError } from "./app-error";

@Catch()
export class AppExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(AppExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const context = host.switchToHttp();
    const request = context.getRequest<Request>();
    const response = context.getResponse<Response>();
    const requestId = request.requestId;

    if (exception instanceof AppError) {
      response.status(exception.statusCode).json({
        error: {
          code: exception.code,
          message: exception.message,
          details: exception.details,
        },
        requestId,
      });
      return;
    }

    if (exception instanceof HttpException) {
      const status = exception.getStatus();
      const payload = exception.getResponse();
      response.status(status).json({
        error: {
          code: `HTTP_${status}`,
          message:
            typeof payload === "string"
              ? payload
              : ((payload as { message?: string }).message ?? "请求失败"),
          details: typeof payload === "object" ? payload : {},
        },
        requestId,
      });
      return;
    }

    this.logger.error(exception);
    response.status(HttpStatus.INTERNAL_SERVER_ERROR).json({
      error: {
        code: "SYSTEM_INTERNAL_ERROR",
        message: "系统内部错误",
        details: {},
      },
      requestId,
    });
  }
}
