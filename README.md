# IOL Property Plus

Corporate website built on Next.js (App Router) and TypeScript, following the
organisation's Corporate Web Architecture Standard (`../Architecture.md`).

This repository is currently a **scaffold**: it satisfies section 2 of the
standard (baseline technology, dependency policy) plus the minimum of sections
3–5 needed for the skeleton to run and pass its own quality gates. Docker
(section 7), AWS/ECS (section 8), the GitLab pipeline (section 9) and the test
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

## Environment variables

Copy `.env.example` to `.env.local` (git-ignored) and fill in real values.

| Variable               | Scope  | Notes                                          |
| ---------------------- | ------ | ---------------------------------------------- |
| `NEXT_PUBLIC_SITE_URL` | public | Embedded in the client bundle. Never a secret. |

Server-only values and secrets are read only from server modules and, in
deployed environments, injected through ECS Secrets Manager / SSM references —
never committed and never placed in `NEXT_PUBLIC_*`.

## Health endpoint

`GET /api/health` → `{ "status": "ok" }`. Unauthenticated, no external
dependency. Intended as the ALB target-group health check.

## Project layout

Standard section 3 layout. Path aliases (`tsconfig.json`):
`@/assets/*`, `@/components/*`, `@/config/*`, `@/lib/*`, `@/server/*`,
`@/styles/*`, `@/types/*`. Use them instead of deep relative imports.

Styling is **Tailwind CSS 4** (`src/app/globals.css` → `@import "tailwindcss"`,
`postcss.config.mjs`). Do not introduce a second styling system.

## Selected dependency versions

Resolved and reviewed against the npm registry on 2026-08-29. `@latest` was used
to _select_ these; only the resolved versions are committed.

| Package                                | Version          | Reason                                                |
| -------------------------------------- | ---------------- | ----------------------------------------------------- |
| `next`                                 | 16.3.3           | Latest stable App Router release.                     |
| `react` / `react-dom`                  | 19.2.8           | Identical versions; satisfy `next`'s `^19` peer.      |
| `eslint-config-next`                   | 16.3.3           | Same release line as `next` (standard section 2.2).   |
| `typescript`                           | 6.0.3            | See deviation below.                                  |
| `eslint`                               | 9.39.5           | See deviation below.                                  |
| `eslint-config-prettier`               | 10.1.8           | `/flat` entry, placed last in the config.             |
| `eslint-plugin-import-x`               | 4.17.1           | Import ordering (standard section 5).                 |
| `eslint-plugin-perfectionist`          | 5.10.1           | Import/member sorting (standard section 5).           |
| `eslint-plugin-unused-imports`         | 4.4.1            | `no-unused-imports` error (standard section 5).       |
| `prettier`                             | 3.9.6            | Stable Prettier 3.                                    |
| `tailwindcss` / `@tailwindcss/postcss` | 4.3.3            | Styling system.                                       |
| `@types/node`                          | 24.13.3          | Pinned to the Node **24** line, not `@latest` (26.x). |
| `@types/react` / `@types/react-dom`    | 19.2.18 / 19.2.5 | Match React 19.2.                                     |

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
