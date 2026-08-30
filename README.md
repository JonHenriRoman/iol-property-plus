# IOL Property Plus

Corporate website built on Next.js (App Router) and TypeScript, following the
organisation's Corporate Web Architecture Standard.

This repository is currently a **scaffold**. In place: baseline technology and
dependency policy, the repository layout, the application rules, lint/format,
strict TypeScript and Zod environment validation, a multi-stage Docker image,
deterministic test suites, the metadata surface (`robots`/`sitemap`/`manifest`,
Open Graph), and a Drizzle client introspected from the live database. **Not yet
in place:** the ECS service, AWS authentication, and the CI/CD pipeline — see
[Not yet implemented](#not-yet-implemented).

## Requirements

| Tool     | Version               | Enforced by                                                          |
| -------- | --------------------- | -------------------------------------------------------------------- |
| Node.js  | 24.19.0 (Node 24 LTS) | `.nvmrc`, `engines.node` (`>=24.0.0`)                                |
| pnpm     | 11.24.0               | `packageManager`, Corepack                                           |
| Docker   | any recent engine     | local image build only                                               |
| Postgres | 16 (local)            | the app connects to an existing database — see [Database](#database) |

## Local development

```sh
corepack enable                        # activates the pinned pnpm
source ~/.nvm/nvm.sh && nvm use         # or: fnm use / asdf install — all read .nvmrc
pnpm install --frozen-lockfile
pnpm dev                               # http://localhost:3000  (Turbopack)
```

| Script              | Purpose                              |
| ------------------- | ------------------------------------ |
| `pnpm dev`          | Development server                   |
| `pnpm build`        | Production build (standalone output) |
| `pnpm start`        | Serve the production build           |
| `pnpm lint`         | ESLint, `--max-warnings=0`           |
| `pnpm lint:fix`     | ESLint with autofix                  |
| `pnpm typecheck`    | `tsc --noEmit`                       |
| `pnpm format`       | Prettier write                       |
| `pnpm format:check` | Prettier check (CI gate)             |
| `pnpm test`         | `vitest run` (unit + integration)    |
| `pnpm test:e2e`     | `playwright test` (desktop + mobile) |
| `pnpm db:pull`      | Re-introspect the database schema    |
| `pnpm db:check`     | Read-only DB connectivity probe      |

## Environment variables

```sh
cp .env.example .env.local             # .env.local is git-ignored
```

`.env`, `.env.local` and `.env.*.local` are all ignored by `.gitignore` and must
never be committed. Deployed environments inject configuration at runtime — never
from a committed file.

`.env.example` (reproduced here) has three blocks:

```ini
# Public — inlined into the browser bundle by Next.js. Never a secret.
NEXT_PUBLIC_SITE_URL=http://localhost:3000

# Server-only — read only from src/server/*. Validated in src/server/env.ts.
APP_ENV=development
GIT_COMMIT_SHA=dev

# Local dev uses trust auth — no credentials. Deployed environments inject a full
# URL via ECS Secrets Manager / SSM; never commit real credentials.
DATABASE_URL=postgresql://localhost:5432/iol_property_plus
```

| Variable               | Scope                                                 | Validated in        | Default                                         |
| ---------------------- | ----------------------------------------------------- | ------------------- | ----------------------------------------------- |
| `NEXT_PUBLIC_SITE_URL` | public — inlined into the client bundle at build time | `src/config/env.ts` | `http://localhost:3000`                         |
| `NODE_ENV`             | server-only                                           | `src/server/env.ts` | set by Next / tooling                           |
| `APP_ENV`              | server-only                                           | `src/server/env.ts` | `development`                                   |
| `GIT_COMMIT_SHA`       | server-only                                           | `src/server/env.ts` | `dev`                                           |
| `DATABASE_URL`         | server-only                                           | `src/server/env.ts` | `postgresql://localhost:5432/iol_property_plus` |

Every variable has a safe default, so **nothing is required for local dev**. The
two Zod schemas each validate once on module load. `src/server/env.ts` opens with
`import 'server-only'`, so `next build` fails if a Client Component pulls it in.
`src/instrumentation.ts` re-validates the server env when the server process
starts; an invalid value makes `register()` throw and every route — including
`/api/health` — return 500 (in ECS the ALB then marks the task unhealthy and the
deployment rolls back).

Server-only values are read only from `src/server/*`; secrets never appear in
`NEXT_PUBLIC_*`, in `.env.example`, or baked into the Docker image.

## Database

The PostgreSQL database `iol_property_plus` (24 tables) **already exists and is
owned in DataGrip**. This repository never creates, alters, or migrates it — it
only introspects.

**How the app connects:**

- `pnpm db:pull` runs `drizzle-kit pull` (read-only `information_schema` /
  `pg_catalog` queries) plus `scripts/fix-generated-schema.mjs`, regenerating
  `src/server/db/schema.ts` and `src/server/db/relations.ts`. Those files are
  generated — do not edit them; they are excluded from ESLint/Prettier but
  type-checked by `tsc`.
- At runtime, `src/server/db/index.ts` (`server-only`) reads
  `serverEnv.DATABASE_URL`, opens a **lazy** `postgres()` connection (postgres.js
  — no connection until the first query) and wraps it with Drizzle. Application
  code imports `@/server/db`, never `@/server/db/schema` directly.
- `drizzle.config.ts` reads `process.env.DATABASE_URL` directly — `drizzle-kit`
  runs outside Next and cannot load the `server-only` env schema.
- `drizzle-kit`'s migration snapshot (`src/server/db/meta/`, `*.sql`) is
  git-ignored; DataGrip owns the DDL.

The local Postgres uses trust auth, so `DATABASE_URL` carries no credentials.
Verify the connection:

```sh
psql "postgresql://localhost:5432/iol_property_plus" -c "\conninfo"
# You are connected to database "iol_property_plus" as user "..." on host "localhost" ... at port "5432".

pnpm db:check
# ok — provinces reachable via generated schema, rows returned: 0
```

Deployed environments receive a full `DATABASE_URL` (with credentials) from ECS
Secrets Manager / SSM at runtime — never `.env.example`, never the image.

## Merge gates

Every one of these must pass before a branch merges. They mirror the standard's
section 10 list and are all run locally with no external network calls.

```sh
pnpm install --frozen-lockfile
pnpm run format:check
pnpm run lint
pnpm run typecheck
pnpm test
pnpm run build
pnpm test:e2e
```

Notes:

- `pnpm exec playwright install chromium` once, before the first `pnpm test:e2e`.
- `pnpm test` (vitest) is fully in-process: `tests/helpers/no-network.ts` throws
  on any non-loopback `fetch`, and the integration DB is `@electric-sql/pglite`
  (in-process Postgres), not the real one. `tests/integration/db.live.test.ts` is
  skipped unless you opt in:

  ```sh
  TEST_DATABASE_URL=postgresql://localhost:5432/iol_property_plus pnpm test
  # → 9 test files, 22 passed (db.live now runs: the live DB still has the 24 generated tables)
  ```

- `pnpm test:e2e` (Playwright) builds the app and serves it locally on `:3100`;
  an e2e fixture fails any test whose page contacts an external origin.
- The container smoke check below is part of the same gate.

## Docker

Multi-stage `Dockerfile` on `node:24.19.0-bookworm-slim` (matches `.nvmrc`):

| Stage     | Does                                                                                                                                                                      |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base`    | `corepack enable` — pnpm resolves to the pinned `11.24.0` from `packageManager`. Never `pnpm@latest`.                                                                     |
| `deps`    | `pnpm install --frozen-lockfile` (all deps — `next build` needs the dev ones).                                                                                            |
| `builder` | `pnpm run build` → `.next/standalone`. `NEXT_PUBLIC_SITE_URL` is a build `ARG` because it is inlined at build time.                                                       |
| `runner`  | Copies only `.next/standalone`, `.next/static`, `public`. No source, no pnpm, no dev dependencies. Runs as non-root `nextjs` (uid/gid 1001). `CMD ["node", "server.js"]`. |

Build and run it locally:

```sh
docker build --pull -t iol-property-plus:local .
docker run -d --name ipp -p 3000:3000 iol-property-plus:local
curl -fsS http://localhost:3000/api/health      # {"status":"ok"}
docker exec ipp id                              # uid=1001(nextjs) gid=1001(nodejs)
docker rm -f ipp && docker rmi iol-property-plus:local
```

Runtime configuration (`APP_ENV`, `GIT_COMMIT_SHA`, `DATABASE_URL`, secrets) is
passed at run time with `docker run -e …` or `--env-file`, never baked in;
`.dockerignore` excludes every `.env*`. To bake a non-default public site URL,
pass `--build-arg NEXT_PUBLIC_SITE_URL=https://your-domain` to `docker build`.

## Not yet implemented

Deployment does not exist in this repository. There is no deploy script, no
infrastructure code, and **no AWS credentials of any kind** — static or
federated. The following are deferred follow-ups:

- **ECS / Fargate service behind an ALB** (standard section 8) — task definition,
  target group health-checking `/api/health`, HTTPS listener, autoscaling, and a
  deployment circuit breaker with automatic rollback. None of it is here.
- **AWS authentication via GitLab OIDC and short-lived STS credentials**
  (standard section 9) — the IAM OIDC identity provider, the narrowly-scoped
  build and deploy roles, and the `assume-role-with-web-identity` exchange. Not
  configured.
- **GitLab CI/CD pipeline** (`.gitlab-ci.yml`, standard section 9) —
  `verify → image → deploy`: run the merge gates, build and push
  `image:${CI_COMMIT_SHA}` to Amazon ECR, register an ECS task-definition
  revision, update the service, and wait for stability. Not present.
- **Base-image digest pin** for the `Dockerfile` (standard section 7) — currently
  the readable tag `node:24.19.0-bookworm-slim`; the digest is recorded in a
  Dockerfile comment for when the pipeline lands.

Until these exist, any deployment is manual and out of band, and this README
documents only what runs locally.

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

The `src/app` → `src/features` → `src/config` / `src/server` boundary is
enforced, not just documented:

- **Build-time:** `src/server/*` imports the `server-only` package. If a Client
  Component pulls a server module into its graph, `next build` fails.
- **Lint-time:** `import-x/no-restricted-paths` zones in `eslint.config.js` fail
  `pnpm lint` on the disallowed edges in the table above.

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
4. file-scoped overrides: `import-x/exports-last` is **off** for
   `src/app/**/*.{ts,tsx}` (Next.js route files co-locate segment config with the
   default export) and for `tests/**` + `*.config.ts`
5. `eslint-config-prettier/flat` — **last**, so it wins every formatting conflict
6. `globalIgnores` for generated output (the Drizzle schema files)

No `.eslintrc`, no `next lint`, no rule disabled globally to paper over a single
file, no `eslint-disable` comments in source. Prettier uses the corporate-sites
profile (`.prettierrc`); `.prettierignore` covers generated output but **not**
`.ts`/`.tsx` — those are format-checked.

## Application notes

- **Server Components by default.** The only Client Component is
  `src/app/error.tsx` — Next.js requires `error.tsx` to be one (browser error
  boundary + `reset()` callback). `global-error.tsx` is deferred.
- **Metadata is driven from `src/config/site.ts`** — no URL or name hardcoded
  elsewhere. Routes: `/robots.txt`, `/sitemap.xml`, `/manifest.webmanifest`, and
  the `next/og`-generated `/icon`, `/apple-icon`, `/opengraph-image` (placeholder
  monograms — replace with real brand assets). Canonical, Open Graph and Twitter
  tags are set in `src/app/layout.tsx`.
- **External images are denied by policy:** `next.config.ts` sets
  `images.remotePatterns: []`. Add a specific `{ protocol, hostname, pathname }`
  entry when genuinely required — never a wildcard hostname.
- `next.config.ts` sets `agentRules: false` so `next build` does not write
  `AGENTS.md` / `CLAUDE.md` into the repository root.

## Selected dependency versions

Resolved and reviewed against the npm registry in August 2026. `@latest` was used
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
| `vitest` (dev)                         | 4.1.10           | Unit + integration runner.                                                                                  |
| `@playwright/test` (dev)               | 1.62.1           | E2E runner (desktop + mobile projects).                                                                     |
| `@electric-sql/pglite` (dev)           | 0.5.4            | In-process Postgres for the integration DB.                                                                 |
| `@axe-core/playwright` (dev)           | 4.12.1           | Accessibility smoke check in e2e.                                                                           |
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

The standard's section 2.2 reference table (snapshot 2026-08-24) lists TypeScript
"latest" and ESLint 10.9.0. Both were validated against the actual
`eslint-config-next@16.3.3` dependency graph and rolled back one major line:

1. **TypeScript 6.0.3, not 7.0.2.** `eslint-config-next@16.3.3` depends on
   `typescript-eslint@8.x`, whose peer range is `typescript >=4.8.4 <6.1.0`. No
   `typescript-eslint` release yet supports TS 7. 6.0.3 is the highest stable
   release inside the supported range. This is exactly section 2.2's rule:
   "latest stable **compatible** with the selected Next.js release".

2. **ESLint 9.39.5, not 10.9.x.** ESLint 10 removed deprecated rule-context APIs
   that `eslint-plugin-react@7.37.5` (bundled by `eslint-config-next@16.3.3`)
   still calls; linting crashes outright with
   `contextOrFilename.getFilename is not a function`. 9.39.5 is the latest ESLint
   9 and resolves every peer in the `eslint-config-next` tree cleanly.

Both should be revisited when `eslint-config-next` ships a release built against
`typescript-eslint` 9 / ESLint 10.

## Ownership

Engineering owns this repository. Deviations from the Corporate Web Architecture
Standard must be recorded here and justified in the merge request.
