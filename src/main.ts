import "reflect-metadata";

import compression from "compression";
import cookieParser from "cookie-parser";
import express from "express";
import helmet from "helmet";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { NestFactory } from "@nestjs/core";
import { ConfigService } from "@nestjs/config";
import { DocumentBuilder, SwaggerModule } from "@nestjs/swagger";
import { RequestMethod, ValidationPipe } from "@nestjs/common";

import { AppModule } from "./app.module";
import { AdminBootstrapService } from "./admin/admin.bootstrap";
import { AppExceptionFilter } from "./common/errors/app-exception.filter";
import { RequestIdMiddleware } from "./common/http/request-id.middleware";

async function bootstrap() {
  const app = await NestFactory.create(AppModule, {
    bufferLogs: true,
  });
  app.enableShutdownHooks();
  const config = app.get(ConfigService);
  const isProduction = config.get("NODE_ENV", "development") === "production";
  const port = config.get<number>("PORT", 3000);
  const host = config.get<string>("HOST", "0.0.0.0");
  if (config.get<boolean>("TRUST_PROXY", false)) {
    app.getHttpAdapter().getInstance().set("trust proxy", 1);
  }

  app.use(helmet({ contentSecurityPolicy: false }));
  app.use(compression());
  app.use(cookieParser());
  app.use(new RequestIdMiddleware().use);
  // AdminJS uses formidable for its own forms; mount it before global JSON parsers.
  await app.get(AdminBootstrapService).register(app);
  app.use(express.json({ limit: "2mb" }));
  app.use(express.urlencoded({ extended: true, limit: "2mb" }));
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );
  app.useGlobalFilters(new AppExceptionFilter());
  app.setGlobalPrefix("api/v1", {
    exclude: [
      { path: "health/(.*)", method: RequestMethod.ALL },
      { path: "events/(.*)", method: RequestMethod.ALL },
      { path: "media/(.*)", method: RequestMethod.ALL },
      { path: "workbench/(.*)", method: RequestMethod.ALL },
    ],
  });

  const origins = config
    .get<string>("FRONTEND_ORIGINS", "http://localhost:3000")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  app.enableCors({
    origin: origins.length === 1 ? origins[0] : origins,
    credentials: true,
  });

  const workbenchRoot = join(process.cwd(), "web", "dist");
  if (existsSync(workbenchRoot)) {
    const staticMiddleware = express.static(workbenchRoot, {
      index: false,
      maxAge: isProduction ? "1d" : 0,
    });
    const httpAdapter = app.getHttpAdapter().getInstance();
    httpAdapter.use("/workbench", staticMiddleware);
    httpAdapter.get(
      "/workbench",
      (_request: unknown, response: express.Response) => {
        response.sendFile(join(workbenchRoot, "index.html"));
      },
    );
    httpAdapter.get(
      "/workbench/*",
      (_request: unknown, response: express.Response) => {
        response.sendFile(join(workbenchRoot, "index.html"));
      },
    );
  }
  app
    .getHttpAdapter()
    .getInstance()
    .get("/", (_request: unknown, response: express.Response) => {
      response.redirect("/workbench/");
    });

  const swaggerConfig = new DocumentBuilder()
    .setTitle("Commerce Studio API")
    .setDescription(
      "AI ecommerce product image and video generation workbench API",
    )
    .setVersion("0.1.0")
    .addCookieAuth("access_token")
    .build();
  const document = SwaggerModule.createDocument(app, swaggerConfig);
  SwaggerModule.setup("api/docs", app, document, {
    swaggerOptions: { persistAuthorization: true },
  });

  await app.listen(port, host);
  const url = await app.getUrl();
  console.log(`commerce-studio listening at ${url}`);
  console.log(`AdminJS: ${url}/admin`);
  console.log(`Workbench: ${url}/workbench`);
}

void bootstrap();
