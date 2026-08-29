import 'server-only';
import { z } from 'zod';

/**
 * Server-only environment schema.
 *
 * `import 'server-only'` fails the build if this module is pulled into a Client
 * Component's graph. Validated once on module load; `src/instrumentation.ts`
 * also imports it at server start so a misconfigured deploy exits at boot.
 *
 * Secrets (e.g. a future DATABASE_URL) are injected at runtime via ECS Secrets
 * Manager / SSM and must never be copied into the image.
 */

const serverEnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']),
  APP_ENV: z.enum(['development', 'staging', 'production']).default('development'),
  GIT_COMMIT_SHA: z.string().min(1).default('dev'),
});

const parsed = serverEnvSchema.safeParse(process.env);

if (!parsed.success) {
  throw new Error(`Invalid server environment:\n${z.prettifyError(parsed.error)}`);
}

type ServerEnv = z.infer<typeof serverEnvSchema>;

const serverEnv: ServerEnv = parsed.data;

export { serverEnv };
export type { ServerEnv };
