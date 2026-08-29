import { z } from 'zod';

/**
 * Public environment schema.
 *
 * `NEXT_PUBLIC_*` values are inlined into the browser bundle by Next.js and are
 * safe to import from a Client Component. Never put a secret here.
 *
 * Next only inlines a *static* `process.env.NEXT_PUBLIC_X` member access, so the
 * object handed to the schema is built with literal keys rather than by passing
 * `process.env`.
 */

const publicEnvSchema = z.object({
  NEXT_PUBLIC_SITE_URL: z.url().default('http://localhost:3000'),
});

const parsed = publicEnvSchema.safeParse({
  NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
});

if (!parsed.success) {
  throw new Error(`Invalid public environment:\n${z.prettifyError(parsed.error)}`);
}

type PublicEnv = z.infer<typeof publicEnvSchema>;

const publicEnv: PublicEnv = parsed.data;

export { publicEnv };
export type { PublicEnv };
