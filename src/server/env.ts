import 'server-only';
import { z } from 'zod';

/**
 * Server-only environment schema.
 *
 * `import 'server-only'` fails the build if this module is pulled into a Client
 * Component's graph. Validated once on module load; `src/instrumentation.ts`
 * also imports it at server start so a misconfigured deploy exits at boot.
 *
 * Deployed environments inject DATABASE_URL (and any future secret) at runtime
 * via ECS Secrets Manager / SSM; secrets must never be copied into the image.
 * Local dev falls back to the trust-auth localhost database.
 */

const serverEnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']),
  APP_ENV: z.enum(['development', 'staging', 'production']).default('development'),
  GIT_COMMIT_SHA: z.string().min(1).default('dev'),
  DATABASE_URL: z
    .url({ protocol: /^postgres(ql)?$/ })
    .default('postgresql://localhost:5432/iol_property_plus'),
  // Propdata feed adapter (Python importer) — optional; the web app never needs them.
  PROP_DATA_API_USERNAME: z.string().min(1).optional(),
  PROP_DATA_API_PASSWORD: z.string().min(1).optional(),
  PROP_DATA_API_LOGIN_URL: z.url().optional(),
});

const parsed = serverEnvSchema.safeParse(process.env);

if (!parsed.success) {
  throw new Error(`Invalid server environment:\n${z.prettifyError(parsed.error)}`);
}

type ServerEnv = z.infer<typeof serverEnvSchema>;

const serverEnv: ServerEnv = parsed.data;

export { serverEnv };
export type { ServerEnv };
