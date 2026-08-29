# IOL Property Plus

Corporate website built on Next.js (App Router) and TypeScript, following the
organisation's Corporate Web Architecture Standard (`../Architecture.md`).

This repository is currently a **scaffold**: it satisfies sections 2–7 of the
standard (baseline technology, dependency policy, repository layout, application
rules, lint/format, TypeScript & environment safety, multi-stage Docker) plus
the metadata surface from section 4.2 and a Drizzle client introspected from the
live database. AWS/ECS (section 8), the GitLab pipeline (section 9) and the test
suites (section 10) are not yet in place.

## Requirements

| Tool    | Version               | Enforced by                           |
| ------- | --------------------- | ------------------------------------- |
| Node.js | 24.19.0 (Node 24 LTS) | `.nvmrc`, `engines.node` (`>=24.0.0`) |
| pnpm    | 11.24.0               | `packageManager`, Corepack            |

```sh
corepack enable          # activates the pinned pnpm
nvm use                  # or: fnm use / asdf — reads .nvmrc
pnpm install --frozen-lockfile
```

## Local development

```sh
pnpm dev                 # http://localhost:3000  (Turbopack)
```

| Script              | Purpose                                |
| ------------------- | -------------------------------------- |
| `pnpm dev`          | Development server                     |
| `pnpm build`        | Production build (standalone output)   |
| `pnpm start`        | Serve the production build             |
| `pnpm lint`         | ESLint, `--max-warnings=0`             |
| `pnpm lint:fix`     | ESLint with autofix                    |
| `pnpm typecheck`    | `tsc --noEmit`                         |
| `pnpm format`       | Prettier write                         |
| `pnpm format:check` | Prettier check (CI gate)               |
| `pnpm test`         | `vitest run` — pending section 10      |
| `pnpm test:e2e`     | `playwright test` — pending section 10 |
| `pnpm db:pull`      | Re-introspect the database schema      |
| `pnpm db:check`     | Read-only DB connectivity probe        |

## Environment variables

Copy `.env.example` to `.env.local` (git-ignored) and fill in real values.
`.env`, `.env.local` and `.env.*.local` are ignored by `.gitignore` and must
never be committed.

Two Zod schemas validate the environment, each once on module load:

| File                | Scope                                                                              | Contents                                                |
| ------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `src/config/env.ts` | public — safe to import from a Client Component                                    | `NEXT_PUBLIC_SITE_URL`                                  |
| `src/server/env.ts` | server-only — `import 'server-only'`, build fails if a Client Component imports it | `NODE_ENV`, `APP_ENV`, `GIT_COMMIT_SHA`, `DATABASE_URL` |

`src/instrumentation.ts` imports `src/server/env.ts` at server start, so an
invalid server environment is caught at boot: `register()` throws, every route
(including `/api/health`) returns 500, the ALB marks the task unhealthy and the
deployment rolls back.

Server-only values are read only from `src/server/*`. Secrets are injected at
runtime through ECS Secrets Manager / SSM references — never committed, never
placed in `NEXT_PUBLIC_*`, never baked into the image. `.env.example` holds
variable names and safe placeholder values only.

## Database

The PostgreSQL schema (`iol_property_plus`, 24 tables) is **owned in DataGrip**.
This repo never creates, alters or migrates it — it only introspects.

| Path                                      | Notes                                                                                                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/server/db/schema.ts`, `relations.ts` | **Generated** by `pnpm db:pull` (`drizzle-kit pull` + `scripts/fix-generated-schema.mjs`). Do not edit. Excluded from ESLint/Prettier, type-checked by `tsc`. |
| `src/server/db/custom-types.ts`           | Hand-written `citext` / `tsvector` column types that `drizzle-kit` can't map.                                                                                 |
| `src/server/db/index.ts`                  | Hand-written `server-only` client. Import **`@/server/db`**, never `@/server/db/schema` directly.                                                             |
| `drizzle.config.ts`                       | `drizzle-kit` config — reads `process.env.DATABASE_URL` (it runs outside Next and can't load the `server-only` env schema).                                   |

`drizzle-kit`'s migration snapshot (`src/server/db/meta/`, `*.sql`) is
git-ignored — DataGrip owns DDL.

`DATABASE_URL` defaults to `postgresql://localhost:5432/iol_property_plus`. The
local instance uses trust auth (no credentials); a deployed instance gets a full
URL from ECS secrets via `.env.local` / the pipeline, never `.env.example`.

- `pnpm db:pull` — re-introspect after a DataGrip schema change.
- `pnpm db:check` — read-only connectivity + schema-match probe against the real database.

## Health endpoint

`GET /api/health` → `{ "status": "ok" }`. Unauthenticated, no external
dependency. `dynamic = 'force-dynamic'` so it is never served from a
prerendered cache. Intended as the ALB target-group health check.

## Docker

Multi-stage `Dockerfile` on `node:24.19.0-bookworm-slim` (matches `.nvmrc`):

| Stage     | Does                                                                                                                                                                      |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base`    | `corepack enable` — pnpm resolves to the pinned `11.24.0` from `packageManager`. Never `pnpm@latest`.                                                                     |
| `deps`    | `pnpm install --frozen-lockfile` (all deps — `next build` needs the dev ones).                                                                                            |
| `builder` | `pnpm run build` → `.next/standalone`. `NEXT_PUBLIC_SITE_URL` is a build `ARG` (inlined at build time; the pipeline passes the real value).                               |
| `runner`  | Copies only `.next/standalone`, `.next/static`, `public`. No source, no pnpm, no dev dependencies. Runs as non-root `nextjs` (uid/gid 1001). `CMD ["node", "server.js"]`. |

```sh
docker build --pull \
  --build-arg NEXT_PUBLIC_SITE_URL=https://your-domain \
  -t iol-property-plus .
docker run -d -p 3000:3000 iol-property-plus
curl http://localhost:3000/api/health          # {"status":"ok"}
```

Runtime config (`APP_ENV`, `GIT_COMMIT_SHA`, `DATABASE_URL`, secrets) is injected
by ECS at run time, never baked in — `.dockerignore` excludes every `.env*`.
`postgres` / `drizzle-orm` are absent from the standalone bundle until a route
imports `@/server/db`; `next build` traces them in at that point.

Base-image digest pin and the pipeline `--build-arg`s are section 9.

## Metadata and SEO

All metadata is driven from `src/config/site.ts` — no URL or name is hardcoded
elsewhere.

| Route                   | Source                                       | Notes                                                                                          |
| ----------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `/robots.txt`           | `src/app/robots.ts`                          | Allows `/`, disallows `/api/`, names the sitemap.                                              |
| `/sitemap.xml`          | `src/app/sitemap.ts`                         | Lists `/` only; add routes as pages are added.                                                 |
| `/manifest.webmanifest` | `src/app/manifest.ts`                        | Name, colours, `display: standalone`, icons.                                                   |
| `/icon`, `/apple-icon`  | `src/app/icon.tsx`, `src/app/apple-icon.tsx` | **Placeholder** monograms rendered by `next/og` at build time. Replace with real brand assets. |
| `/opengraph-image`      | `src/app/opengraph-image.tsx`                | 1200×630 **placeholder**; also used for the Twitter card.                                      |

Canonical URL, Open Graph and Twitter tags are set in `src/app/layout.tsx`.

External images are denied by policy: `next.config.ts` sets
`images.remotePatterns: []`. Add a specific `{ protocol, hostname, pathname }`
entry when an external image is genuinely required — never a wildcard hostname.

## Client Components

Server Components are the default. The only Client Component is:

| File                | Why                                                                                                                                                                                                                           |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/app/error.tsx` | Next.js requires `error.tsx` to be a Client Component: it runs a browser error boundary and receives a `reset()` callback. Also uses `useEffect` to log. It is a leaf route file — the boundary is already as low as it goes. |

`global-error.tsx` (a second Client Component) is deferred until root-layout
failure handling is actually needed.

## Project layout

Architecture Standard section 3. Import via the `@/*` aliases below, never deep
relative paths.

| Path                           | Alias            | What belongs here                                                                                                              |
| ------------------------------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `src/app/`                     | —                | Route files only. Keep them thin: parse input, call a feature or service, map the response. No business logic.                 |
| `src/app/api/*/route.ts`       | —                | Route handlers. Validate, delegate, return a status.                                                                           |
| `src/features/<feature>/`      | `@/features/*`   | One self-contained vertical. `index.ts` is the **only** public entry point; nothing outside the feature imports its internals. |
| `src/components/layout/`       | `@/components/*` | Header, footer, navigation, page shell.                                                                                        |
| `src/components/sections/`     | `@/components/*` | Page sections shared by more than one feature.                                                                                 |
| `src/components/ui/`           | `@/components/*` | Small generic primitives. Must not import a feature or server code.                                                            |
| `src/config/`                  | `@/config/*`     | Typed public/site configuration. Browser-safe values only.                                                                     |
| `src/lib/`                     | `@/lib/*`        | Framework-neutral helpers, grouped by responsibility. May not import from `app`, `server`, `features` or `components`.         |
| `src/server/`                  | `@/server/*`     | Server-only integrations. Every file starts with `import 'server-only'`. Never reached from a Client Component.                |
| `src/styles/`                  | `@/styles/*`     | Design tokens and global style fragments.                                                                                      |
| `src/types/`                   | `@/types/*`      | Shared domain types.                                                                                                           |
| `src/assets/`                  | `@/assets/*`     | Images, SVGs and fonts imported by `src/` code (not the ones served raw from `public/`).                                       |
| `public/{fonts,icons,images}/` | —                | Static files served at the URL root.                                                                                           |
| `tests/unit/`                  | —                | Fast, isolated. No network, no database.                                                                                       |
| `tests/integration/`           | —                | Several modules together. Still deterministic and offline.                                                                     |
| `tests/e2e/`                   | —                | Playwright browser journeys against a locally built app.                                                                       |

The `src/app` → `src/features` → `src/config` / `src/server` boundary is enforced,
not just documented:

- **Build-time:** `src/server/*` imports the `server-only` package. If a Client
  Component pulls a server module into its graph, `next build` fails.
- **Lint-time:** `import-x/no-restricted-paths` zones in `eslint.config.js` fail
  `pnpm lint` on the disallowed edges in the table above.

`src/server/release-info.ts` is a scaffold-time affordance (deploy identity from
env). It can be folded into the section 6 env schema once the section 9 pipeline
injects `GIT_COMMIT_SHA` / `APP_ENV`.

Styling is **Tailwind CSS 4** (`src/app/globals.css` → `@import "tailwindcss"`,
`postcss.config.mjs`). Do not introduce a second styling system.

## Lint and format

`eslint.config.js` is flat config, composed in the order the Architecture
Standard section 5 prescribes:

1. `@eslint/js` recommended
2. `eslint-config-next` — `core-web-vitals`, then `typescript`
3. project rules — `import-x/*` (including the section 3 `no-restricted-paths`
   zones), `perfectionist/*`, `sort-vars`, `unused-imports/*`, `no-debugger`,
   `prefer-const`
4. one file-scoped override: `import-x/exports-last` is **off** for
   `src/app/**/*.{ts,tsx}` because Next.js route files co-locate segment config
   (`export const metadata`, `size`, `dynamic`) with the default export
5. `eslint-config-prettier/flat` — **last**, so it wins every formatting conflict
6. `globalIgnores` for generated output

No `.eslintrc`, no `next lint`, no rule disabled globally to paper over a single
file, no `eslint-disable` comments in source. Prettier uses the corporate-sites
profile (`.prettierrc`); `.prettierignore` covers generated output but **not**
`.ts`/`.tsx` — those are format-checked.

## Selected dependency versions

Resolved and reviewed against the npm registry on 2026-08-29. `@latest` was used
to _select_ these; only the resolved versions are committed.

| Package                                | Version          | Reason                                                                                                      |
| -------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------- |
| `next`                                 | 16.3.3           | Latest stable App Router release.                                                                           |
| `react` / `react-dom`                  | 19.2.8           | Identical versions; satisfy `next`'s `^19` peer.                                                            |
| `server-only`                          | 0.0.1            | Build-time server/client boundary guard (React team).                                                       |
| `zod`                                  | 4.4.3            | Runtime env-schema validation (section 6). Held at 4.4.x — the 4.5 line published hours before this change. |
| `drizzle-orm`                          | 0.45.2           | Typed DB client over the introspected schema.                                                               |
| `postgres`                             | 3.4.9            | PostgreSQL driver (postgres.js) — pure JS, no native build.                                                 |
| `drizzle-kit` (dev)                    | 0.31.10          | `drizzle-kit pull` introspection.                                                                           |
| `tsx` (dev)                            | 4.22.5           | Runs `scripts/*.ts` (`pnpm db:check`). Held ~2 months back from latest.                                     |
| `@eslint/js`                           | 9.39.5           | ESLint recommended config; pinned to the `eslint` version.                                                  |
| `eslint-config-next`                   | 16.3.3           | Same release line as `next` (standard section 2.2).                                                         |
| `typescript`                           | 6.0.3            | See deviation below.                                                                                        |
| `eslint`                               | 9.39.5           | See deviation below.                                                                                        |
| `eslint-config-prettier`               | 10.1.8           | `/flat` entry, placed last in the config.                                                                   |
| `eslint-plugin-import-x`               | 4.17.1           | Import ordering (standard section 5).                                                                       |
| `eslint-plugin-perfectionist`          | 5.10.1           | Import/member sorting (standard section 5).                                                                 |
| `eslint-plugin-unused-imports`         | 4.4.1            | `no-unused-imports` error (standard section 5).                                                             |
| `prettier`                             | 3.9.6            | Stable Prettier 3.                                                                                          |
| `tailwindcss` / `@tailwindcss/postcss` | 4.3.3            | Styling system.                                                                                             |
| `@types/node`                          | 24.13.3          | Pinned to the Node **24** line, not `@latest` (26.x).                                                       |
| `@types/react` / `@types/react-dom`    | 19.2.18 / 19.2.5 | Match React 19.2.                                                                                           |

### Approved deviations from the standard

The standard's section 2.2 reference table (snapshot 2026-08-24) lists
TypeScript "latest" and ESLint 10.9.0. Both were validated against the actual
`eslint-config-next@16.3.3` dependency graph and rolled back one major line:

1. **TypeScript 6.0.3, not 7.0.2.** `eslint-config-next@16.3.3` depends on
   `typescript-eslint@8.x`, whose peer range is `typescript >=4.8.4 <6.1.0`.
   No `typescript-eslint` release yet supports TS 7. 6.0.3 is the highest
   stable release inside the supported range. This is exactly section 2.2's
   rule: "latest stable **compatible** with the selected Next.js release".

2. **ESLint 9.39.5, not 10.9.x.** ESLint 10 removed deprecated rule-context
   APIs that `eslint-plugin-react@7.37.5` (bundled by `eslint-config-next@16.3.3`)
   still calls; linting crashes outright with
   `contextOrFilename.getFilename is not a function`. 9.39.5 is the latest
   ESLint 9 and resolves every peer in the `eslint-config-next` tree cleanly.

Both should be revisited when `eslint-config-next` ships a release built against
`typescript-eslint` 9 / ESLint 10.

`next.config.ts` sets `agentRules: false` so `next build` does not write
`AGENTS.md` / `CLAUDE.md` into the repository root.

## Ownership

Engineering owns this repository. Deviations from the Corporate Web
Architecture Standard must be recorded here and justified in the merge request.
