const booleanValue = (value: string | undefined, fallback: boolean) => {
  if (value === undefined) return fallback;
  return value.toLowerCase() === "true";
};

type ValidatedConfig = Record<string, unknown> & {
  NODE_ENV: string;
  PORT: number;
  HOST: string;
  DATABASE_REQUIRED: boolean;
  DATABASE_URL?: string;
  TRUST_PROXY: boolean;
  COOKIE_SECURE: boolean;
  MAX_UPLOAD_BYTES: number;
  GENERATION_WORKER_ENABLED: boolean;
  GENERATION_POLL_INTERVAL_MS: number;
  GENERATION_MAX_RETRIES: number;
  MODEL_REQUEST_TIMEOUT_MS: number;
  MODEL_DOWNLOAD_TIMEOUT_MS: number;
};

export function validateEnv(config: Record<string, unknown>) {
  const nodeEnv = String(config.NODE_ENV ?? "development");
  const databaseRequired = booleanValue(
    String(config.DATABASE_REQUIRED ?? ""),
    nodeEnv === "production",
  );

  const result: ValidatedConfig = {
    ...config,
    NODE_ENV: nodeEnv,
    PORT: Number(config.PORT ?? 3000),
    HOST: String(config.HOST ?? "0.0.0.0"),
    DATABASE_URL: config.DATABASE_URL ? String(config.DATABASE_URL) : undefined,
    DATABASE_REQUIRED: databaseRequired,
    ADMINJS_WATCH: booleanValue(String(config.ADMINJS_WATCH ?? ""), false),
    TRUST_PROXY: booleanValue(String(config.TRUST_PROXY ?? ""), false),
    COOKIE_SECURE: booleanValue(
      String(config.COOKIE_SECURE ?? ""),
      nodeEnv === "production",
    ),
    MAX_UPLOAD_BYTES: Number(config.MAX_UPLOAD_BYTES ?? 50 * 1024 * 1024),
    GENERATION_WORKER_ENABLED: booleanValue(
      String(config.GENERATION_WORKER_ENABLED ?? ""),
      true,
    ),
    GENERATION_POLL_INTERVAL_MS: Number(
      config.GENERATION_POLL_INTERVAL_MS ?? 5000,
    ),
    GENERATION_MAX_RETRIES: Number(config.GENERATION_MAX_RETRIES ?? 2),
    MODEL_REQUEST_TIMEOUT_MS: Number(config.MODEL_REQUEST_TIMEOUT_MS ?? 30000),
    MODEL_DOWNLOAD_TIMEOUT_MS: Number(
      config.MODEL_DOWNLOAD_TIMEOUT_MS ?? 120000,
    ),
  };

  if (result.DATABASE_REQUIRED && !result.DATABASE_URL) {
    throw new Error("DATABASE_URL is required when DATABASE_REQUIRED=true");
  }
  if (result.NODE_ENV === "production") {
    for (const key of [
      "JWT_SECRET",
      "APP_ENCRYPTION_KEY",
      "ADMIN_COOKIE_PASSWORD",
    ]) {
      if (!result[key] || String(result[key]).startsWith("replace-")) {
        throw new Error(`${key} must be configured in production`);
      }
    }
  }
  return result;
}
