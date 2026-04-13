import { z } from "zod";

// ─── Schema definitions ──────────────────────────────────────────────────────

const serverEnvSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),

  // API
  NEXT_PUBLIC_API_URL: z.string().url().default("http://localhost:8000"),
  NEXTAUTH_URL: z.string().url().default("http://localhost:3000"),
  NEXTAUTH_SECRET: z.string().min(32),

  // Database
  DATABASE_URL: z.string().url(),

  // Redis
  REDIS_URL: z.string().url().default("redis://localhost:6379/0"),

  // S3 / MinIO
  S3_ENDPOINT_URL: z.string().url().optional(),
  S3_ACCESS_KEY_ID: z.string(),
  S3_SECRET_ACCESS_KEY: z.string(),
  S3_REGION: z.string().default("us-east-1"),
  MINIO_BUCKET_COSTS: z.string().default("atlas-cost-reports"),
  MINIO_BUCKET_EXPORTS: z.string().default("atlas-exports"),
});

const clientEnvSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url().default("http://localhost:8000"),
  NEXT_PUBLIC_APP_URL: z.string().url().default("http://localhost:3000"),
});

// ─── Type exports ────────────────────────────────────────────────────────────

export type ServerEnv = z.infer<typeof serverEnvSchema>;
export type ClientEnv = z.infer<typeof clientEnvSchema>;

// ─── Validation helpers ──────────────────────────────────────────────────────

export function validateServerEnv(env: Record<string, string | undefined>): ServerEnv {
  const parsed = serverEnvSchema.safeParse(env);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((i) => `  • ${i.path.join(".")}: ${i.message}`)
      .join("\n");
    throw new Error(`Invalid server environment variables:\n${issues}`);
  }
  return parsed.data;
}

export function validateClientEnv(env: Record<string, string | undefined>): ClientEnv {
  const parsed = clientEnvSchema.safeParse(env);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((i) => `  • ${i.path.join(".")}: ${i.message}`)
      .join("\n");
    throw new Error(`Invalid client environment variables:\n${issues}`);
  }
  return parsed.data;
}

export { serverEnvSchema, clientEnvSchema };
