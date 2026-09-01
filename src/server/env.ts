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

/**
 * Optional feed-adapter var: an empty string (from `cp .env.example .env.local`,
 * where every one of these is a blank placeholder) is treated as "unset" rather
 * than failing validation. Only the Python importers read these; the web app
 * never does.
 */
const optional = <T extends z.ZodType>(schema: T) =>
  z.preprocess((v) => (v === '' ? undefined : v), schema.optional());

const serverEnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']),
  APP_ENV: z.enum(['development', 'staging', 'production']).default('development'),
  GIT_COMMIT_SHA: z.string().min(1).default('dev'),
  DATABASE_URL: z
    .url({ protocol: /^postgres(ql)?$/ })
    .default('postgresql://localhost:5432/iol_property_plus'),
  // Propdata feed adapter (Python importer).
  PROP_DATA_API_USERNAME: optional(z.string().min(1)),
  PROP_DATA_API_PASSWORD: optional(z.string().min(1)),
  PROP_DATA_API_LOGIN_URL: optional(z.url()),
  // PropCtrl feed adapter (Python importer).
  PROPCTRL_API_USERNAME: optional(z.string().min(1)),
  PROPCTRL_API_PASSWORD: optional(z.string().min(1)),
  PROPCTRL_API_BASE_URL: optional(z.url()),
  // RE/MAX feed adapter (Python importer) — AWS SigV4 + usage-plan key.
  REMAX_ACCESS_KEY: optional(z.string().min(1)),
  REMAX_SECRET_KEY: optional(z.string().min(1)),
  REMAX_API_KEY: optional(z.string().min(1)),
  REMAX_API_BASE_URL: optional(z.url()),
  // Entegral feed adapter (Python importer) — HTTP Basic.
  ENTEGRAL_USERNAME: optional(z.string().min(1)),
  ENTEGRAL_PASSWORD: optional(z.string().min(1)),
  ENTEGRAL_API_BASE_URL: optional(z.url()),
  // PropertyEngine feed adapter (Python importer) — Gumtree Pro standard template.
  // URL pending from PropertyEngine; auth optional ("Authorization may be implemented").
  PROPERTYENGINE_FEED_URL: optional(z.url()),
  PROPERTYENGINE_FEED_AUTH_TOKEN: optional(z.string().min(1)),
  PROPERTYENGINE_FEED_AUTH_SCHEME: optional(z.enum(['bearer', 'basic'])),
  // Fusion FeedStore feed adapter (Python importer) — event-sourced XML sync.
  // FUSION_PASSWORD feeds the per-call SecurityToken digest; still a raw credential.
  FUSION_CLIENT_ID: optional(z.string().min(1)),
  FUSION_PASSWORD: optional(z.string().min(1)),
  FUSION_API_BASE_URL: optional(z.url()),
  // AllSA Property feed adapter (Python importer) — public, unauthenticated.
  // The per-agency `agencyid` is on the feed_sources row, not here; this only
  // overrides the default endpoint host.
  ALLSA_FEED_BASE_URL: optional(z.url()),
  // MyRoof feed adapter (Python importer) — per-franchise bracket-KV feed. The
  // opaque feed token is on the feed_sources row (auth_config->>'token'), not
  // here; this only overrides the default host.
  MYROOF_FEED_BASE_URL: optional(z.url()),
  // PropertyPost feed adapter (Python importer) — one static per-agency URL, a
  // plain GET with no credential. The full feed URL is on the feed_sources row
  // (base_url); this only supplies a default host for a row that omits it.
  PROPERTYPOST_FEED_BASE_URL: optional(z.url()),
  // Re-hosted listing media: directory the /media route handler serves from.
  // Defaults to <repo>/data/media when unset (see src/app/media/[...path]/route.ts).
  MEDIA_ROOT_DIR: optional(z.string().min(1)),
});

const parsed = serverEnvSchema.safeParse(process.env);

if (!parsed.success) {
  throw new Error(`Invalid server environment:\n${z.prettifyError(parsed.error)}`);
}

type ServerEnv = z.infer<typeof serverEnvSchema>;

const serverEnv: ServerEnv = parsed.data;

export { serverEnv };
export type { ServerEnv };
