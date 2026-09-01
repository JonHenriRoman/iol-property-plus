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
| `MEDIA_ROOT_DIR`       | server-only                                           | `src/server/env.ts` | `<repo>/data/media`                             |

`MEDIA_ROOT_DIR` is the directory `src/app/media/[...path]/route.ts` serves
re-hosted listing photos from; the feed importers write there. The feed-adapter
credentials (`PROP_DATA_*`, `PROPCTRL_*`, `REMAX_*`, `ENTEGRAL_*`,
`PROPERTYENGINE_FEED_*`, `FUSION_*`, `ALLSA_FEED_BASE_URL`,
`MYROOF_FEED_BASE_URL`, `PROPERTYPOST_FEED_BASE_URL`, `RT3_FEED_BASE_URL`) are
also server-only and optional — the web app never reads them; only the Python
importers do. `FUSION_PASSWORD` feeds the per-call Fusion SecurityToken digest
but is still a raw credential. AllSA, PropertyPost and RT3 need no credentials
(all three feeds are public); MyRoof's per-franchise feed token lives on its
`feed_sources` row (`auth_config->>'token'`), each PropertyPost agency's full
feed URL lives on its own row (`base_url`), and each RT3 agency's province list
lives on its row (`auth_config->>'provinces'`), not in an env var; the
`*_FEED_BASE_URL` vars only override the default endpoint host. `PROPERTYENGINE_FEED_URL` is still
blank pending the URL from PropertyEngine (the Gumtree Pro schema doc specifies
the file format only); `PROPERTYENGINE_FEED_AUTH_TOKEN` /
`PROPERTYENGINE_FEED_AUTH_SCHEME` (`bearer` | `basic`) are only used if that URL
turns out to need authentication. See each feed-adapter subsection under
[Seed data](#seed-data).

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
owned in DataGrip**. This repository does not run migrations against it — it
introspects the live schema. The one exception is reviewed DDL checked in under
`db/migrations/`, which a maintainer applies by hand in DataGrip (see
[Seed data](#seed-data)); the app still only reads the introspected result.

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

## Seed data

The geography spine (`provinces`, `cities`, `suburbs` — Domain 1 of
`canonical-database-design.md`) is seeded from Property24's public, unauthenticated
suburb CSV. **This project covers South Africa only**: every other country in the
feed is counted for visibility and dropped before any row reaches the database.

The importer is a self-contained Python subproject under [`importers/`](importers/)
(uv + psycopg 3 + pytest — the main app is TypeScript, and there was no prior
Python importer to match). It has its own [README](importers/README.md).

**One-time prerequisite** — the feed carries an `Extension`, a stable `Id`, and an
`Alternate Names` value that the current `suburbs` table has nowhere to store.
Apply the reviewed migration, then re-introspect:

```sh
# in DataGrip, run:
db/migrations/001_suburbs_property24_columns.sql
# then, from the repo root:
pnpm db:pull
```

**Seed:**

```sh
uv sync --project importers            # once

pnpm run seed:suburbs:download         # -> data/property24/suburbs-<UTC>.csv (the only network call)
pnpm run seed:suburbs                  # parse newest download, upsert South African rows
```

Re-runs are idempotent — rows are upserted on Property24's `Id` (`external_id`),
so a refreshed download updates in place instead of duplicating. `data/` is
git-ignored. Add `--dry-run` to resolve and diff without writing.

### Feed infrastructure

`importers/src/iol_importers/feeds/` is the shared bookkeeping every vendor feed
importer will use (Domain 6): it opens an `import_jobs` row when a run starts,
closes it as `Success` / `PartialSuccess` / `Failed` with accurate counts, and
writes one `import_errors` row per failed record without a bad record stopping the
run. Tracking runs on its own autocommit connection, so a rolled-back or crashed
importer still leaves a closed job row. No vendor parsing yet — that lands with
each feed.

Prerequisite: apply `db/migrations/002_feed_infrastructure.sql` in DataGrip (it
replaces `feed_sources.ttl_minutes` with `ttl_days`, and adds
`import_jobs.records_skipped` / `error_message`), then `pnpm db:pull`. See
[`importers/README.md`](importers/README.md) for the API and a runnable demo.

### Listing importer

`importers/src/iol_importers/listings/` turns already-parsed vendor listing
records into `listings` rows (Domain 4): normalises `listing_type` to the enum,
resolves `property_type` (via a per-feed `property_type_vendor_mappings` table),
`suburb` (NULL when unresolved), `agency` / `agent` (via the `*_vendor_ids`
tables), and upserts on `UNIQUE (feed_source_id, vendor_listing_id)`. Price history
and `expires_at` stay with the existing DB triggers. Failed records go to
`import_errors` and the batch continues. Feed-format parsing is a later task.

Prerequisite: apply `db/migrations/003_listings_importer.sql` in DataGrip **after
002** (003 makes `listings.suburb_id` nullable, adds
`property_type_vendor_mappings`, and rewrites `trg_listings_set_expiry` for
`ttl_days` — 002 breaks it otherwise), then `pnpm db:pull`.

### Listing-expiry sweep

`importers/src/iol_importers/lifecycle/` — the expiry-first lifecycle. One atomic
`UPDATE listings SET status = 'Expired', expired_at = now() WHERE status =
'Active' AND expires_at < now()`: touches only `status` + `expired_at`, never
deletes, idempotent, reads live `expires_at`. Needs no migration. Run it with
`uv run --project importers iol-expire-listings`; intended to run nightly (cron
`15 2 * * *`) after the feed imports — see [`importers/README.md`](importers/README.md).

### Propdata feed adapter

`importers/src/iol_importers/propdata/` — the first real vendor feed. HTTP Basic
login → one bearer token per client; the token is **renewed** (not
re-authenticated) each run and kept server-side only, never logged. Pulls the
four listing categories (residential / commercial / holiday / projects) with full
pagination and feeds each through the listing importer, tagged by
`vendor_listing_type`. Credentials live in `.env.local`
(`PROP_DATA_API_USERNAME` / `PROP_DATA_API_PASSWORD`); `.env.example` and
`src/server/env.ts` carry them as optional. Field mappings not verifiable against
the live API are flagged in `propdata/MAPPING_NOTES.md`, not guessed. See
[`importers/README.md`](importers/README.md).

### PropCtrl feed adapter

`importers/src/iol_importers/propctrl/` — the second real vendor feed, and the
CRM behind `iolproperty.co.za` itself (PropCtrl Listing Service v1, an OpenAPI
service whose contract was discovered from `https://api.propctrl.com/v1-listing/swagger.json`,
not assumed). HTTP Basic on every request — no token. A **delta feed**:
`GET /listing/v1/listings/changes?fromDate=` yields change items and a
`nextFromDate` cursor (checkpointed to `data/propctrl/checkpoint.json`), then
listings are fetched **10 ids at a time**. `Removed` items and non-`Active`
listings are skipped and counted. **Read-only** — the `PUT` status write-back
half of the partner protocol is deliberately not implemented. Credentials
(`PROPCTRL_API_USERNAME` / `PROPCTRL_API_PASSWORD` / `PROPCTRL_API_BASE_URL`) live
in `.env.local`; `.env.example` and `src/server/env.ts` carry them as optional.
Uncertain mappings are flagged in `propctrl/MAPPING_NOTES.md`. See
[`importers/README.md`](importers/README.md).

### RE/MAX feed adapter

`importers/src/iol_importers/remax/` — the third vendor feed. An AWS API Gateway
deployment: every request is **AWS SigV4-signed** (`execute-api`, `eu-west-1` —
hand-rolled in `remax/signing.py`, stdlib only) **and** carries an `x-api-key`
header; responses are double-encoded (`data` is a JSON string). Three sync paths:
**full** (`/agents-page` per agent), **incremental** (`/lists-pagenate` since the
`data/remax/checkpoint.json` cursor, then `/listing` per change — the doc's
`/lists` endpoint is HTTP 500), and **deleted** (`/lists_deleted` →
`lifecycle.withdraw_listings`, a soft-delete to `status='Withdrawn'`, never a row
removal). `date_last_updated` skips unchanged listings; `504`s are retried.
Credentials (`REMAX_ACCESS_KEY` / `REMAX_SECRET_KEY` / `REMAX_API_KEY` /
`REMAX_API_BASE_URL`) live in `.env.local`; `.env.example` and `src/server/env.ts`
carry them as optional. Deviations and unmapped fields are in
`remax/MAPPING_NOTES.md`. See [`importers/README.md`](importers/README.md).

### Entegral feed adapter

`importers/src/iol_importers/entegral/` — the fourth vendor feed, and a **pull**
feed (not the push Sync API in Entegral's public docs — confirmed with Entegral
directly). Two HTTP Basic-auth `GET` endpoints on `sync.entegral.net`:
`/api/officeslist` lists the syndicating offices, then
`/api/listings?type=officelistings&ref=…` returns each office's full active set.
There is no deletions endpoint, so removals are caught by **per-office
reconciliation** (`lifecycle.withdraw_missing`, a soft-delete scoped by
`raw_data ->> 'entegral_office_reference'`, guarded against empty responses).
Credentials (`ENTEGRAL_USERNAME` / `ENTEGRAL_PASSWORD`) live in `.env.local`;
`.env.example` and `src/server/env.ts` carry them as optional. Every rendered
Entegral listing must show the agent and office name — the mapper enforces it.
Deviations, unmapped fields, and the **out-of-scope obligations** (lead emails to
the agent **and** `support@entegral.net`; no third-party data handoff; the open
decision on a listing deep-link pattern) are in `entegral/MAPPING_NOTES.md`. See
[`importers/README.md`](importers/README.md).

### PropertyEngine feed adapter

`importers/src/iol_importers/propertyengine/` — the fifth vendor feed.
PropertyEngine syndicates to us using **Gumtree Pro's "Real Estate Standard
Template Feed" v1.0.1** schema (a single full-resend file). The doc specifies
JSON; the only PropertyEngine feed observed in practice is XML with the same
field semantics, so `decode.py` auto-detects and normalises both. `Location`
values (the doc's Appendix A gazetteer) resolve through a checked-in
`locations.csv` (transcribed from the PDF, verified against the SA bounding box);
`Type` values map through the full Appendix B vocabulary, and a value outside it
is quarantined (`error_type='validation'`) rather than defaulted. Removals are
caught by reconciliation (`lifecycle.withdraw_missing`) plus the expiry sweep.
The feed **URL is still pending from PropertyEngine** — `PROPERTYENGINE_FEED_URL`
is blank; run `propertyengine-import --file <path>` against a local file until it
lands. Optional auth (`PROPERTYENGINE_FEED_AUTH_TOKEN` /
`PROPERTYENGINE_FEED_AUTH_SCHEME`) is off unless set. Details and the full list of
what still needs to come from PropertyEngine are in
`propertyengine/MAPPING_NOTES.md`. See [`importers/README.md`](importers/README.md).

### Fusion FeedStore feed adapter

`importers/src/iol_importers/fusion/` — the sixth vendor feed, and the first
that is **not** a REST pull. Private Property SA's Fusion FeedStore is an
**event-sourced XML sync**: four POST methods on `…/v1/sync/`, each signed with a
fresh per-call SecurityToken (`base64(sha1(f"{timeStamp}*{password}*{salt}"))`).
A first run issues `RequestSnapshot` then drains `GetChanges` across however many
calls the snapshot takes; later runs resume from the saved `commitToken`, which
is persisted only after a batch is fully applied (the doc's "omit the token to
replay the last batch" recovery). `<Listing>` events feed `import_listings`
(keyed on the Fusion id, never `fusionRef`); `<Delete>` soft-deletes
(`withdraw_listings` for listings, `status='Inactive'` for offices/agents);
`<Office>`/`<Agent>` upsert `agencies`/`agents`; `<AreaTree>` builds a
`data/fusion/area_tree.json` suburb crosswalk fed to `resolve_suburb` (no
parallel geography table); `<Development>` is deferred to a sidecar + `raw_data`.
Photos are hotlinked. Credentials (`FUSION_CLIENT_ID` / `FUSION_PASSWORD` /
`FUSION_API_BASE_URL`) live in `.env.local`; `.env.example` and `src/server/env.ts`
carry them as optional. `NotifyChangesAvailable` (Fusion's inbound webhook) and
canonical `developments` sync are follow-ups — see
[Not yet implemented](#not-yet-implemented) and `fusion/MAPPING_NOTES.md`. See
[`importers/README.md`](importers/README.md).

### AllSA Property feed adapter

`importers/src/iol_importers/allsa/` — the seventh vendor feed. The public,
unauthenticated `iol.ashx` XML feed: one HTTP GET returns an agency's whole book
as `<Listings><Property>…</Property></Listings>` (flat, no office grouping). Full
resend on every pull, like PropertyEngine — parse, map, `import_listings`, then
`lifecycle.withdraw_missing` for absences. **Each agency is its own `feed_sources`
row** with the `agencyid` in `auth_config->>'agency_id'` — no agency id in the
source. One agency's feed spans several offices, keyed on `BranchId` (not
`Agency_Location`), which upsert `agencies`/`agents`. `<Features>` is a free-form
bag parsed by iterating the actual child elements against a registry (known →
typed columns/labels, unknown → `raw_data` + a per-run tally), de-duplicating
tags the real feed repeats hundreds of times. `Heading` is the title; `Title` is
tenure. Photos hotlinked. `ALLSA_FEED_BASE_URL` (optional, override only) is in
`.env.example` and `src/server/env.ts`. See `allsa/MAPPING_NOTES.md` and
[`importers/README.md`](importers/README.md).

### MyRoof feed adapter

`importers/src/iol_importers/myroof/` — the eighth vendor feed and the first built
on the shared bracketed-KV parser (`iol_importers.bracket_kv`), not a
reimplementation. Per-franchise feed at `https://rat.myroof.co.za/{token}`; one
GET returns the franchise's whole book. Full resend → parse, map,
`import_listings`, `lifecycle.withdraw_missing` for absences. **Each franchise is
its own `feed_sources` row** with the opaque `{token}` in `auth_config->>'token'`
— never in the source, an env var, or a log line. The whole feed is
bank-repossessed stock: every record gets a synthetic `Repossession` feature and
`Agent_Name` is a lender-program label (used as the agent name, `Email` is the id).
`Description`'s literal `<p>` tags are converted to newlines; `GPS` `"lat,lng"`
splits (bare-comma sentinel → NULL); `Type` crosswalks to `property_types`
(`Guest House` unmapped → quarantine). Every unlisted key is kept under
`raw_data.myroof_<Key>`. Photos hotlinked. `MYROOF_FEED_BASE_URL` (optional,
override only) is in `.env.example` and `src/server/env.ts`. See
`myroof/MAPPING_NOTES.md` and [`importers/README.md`](importers/README.md).

### PropertyPost feed adapter

`importers/src/iol_importers/propertypost/` — the ninth vendor feed, one of the
three bracket-KV vendors (RT3, MyRoof, PropertyPost), on the same shared
`iol_importers.bracket_kv` parser. One static per-agency URL (e.g.
`http://lms.propertypost.co.za/BstProperties.txt`, redirecting to HTTPS), a plain
GET with **no credential of any kind** — the full URL lives on the agency's
`feed_sources` row (`base_url`). Full resend → parse, map, `import_listings`,
`lifecycle.withdraw_missing` for absences. One file carries both `For Sale` and
`To Let`; the sampled feed is a single agency, but agency identity is resolved
per record from `Branch_ID`/`Branch_Name` and the distinct-branch count is
reported on every run. `Beds`/`Baths` duplicate `Bedrooms`/`Bathrooms` — coalesced,
never double-counted, a genuine disagreement flagged not dropped. `GPS` is simply
absent when there are no coordinates (no sentinel). `Carports` → `parking_spaces`,
`Verified` → `vendor_updated_at`, missing `Heading` → a synthesized title.
`Features_Description` (unstructured prose) and every other unlisted key are kept
under `raw_data.propertypost_<Key>`, never parsed; `Admin_ID` is a company contact
kept distinct from the agent. Photos hotlinked. `PROPERTYPOST_FEED_BASE_URL`
(optional, override only) is in `.env.example` and `src/server/env.ts`. See
`propertypost/MAPPING_NOTES.md` and [`importers/README.md`](importers/README.md).

### RT3 (Rawson) feed adapter

`importers/src/iol_importers/rt3/` — the tenth vendor feed; the last of the three
bracket-KV vendors on the shared `iol_importers.bracket_kv` parser. One
bracket-KV file per province at
`https://webservices.rawsonproperties.co.za/iol-{Province}.txt`, a plain public
GET with **no auth of any kind**. RT3 is a single brand ("Rawson Properties");
what is per-agency is _which province files_ it publishes — a JSON array of URL
tokens on the `feed_sources` row (`auth_config->>'provinces'`). Every configured
province is fetched up front (any fetch failure aborts before anything is
imported or reconciled), all imported in one job, then **reconciled per province**
via `withdraw_missing(raw_scope=("rt3_province", province))` so a broken or
missing province can't withdraw another's listings. `Branch_ID`/`Branch_Name` are
the per-listing office identity used as the agency. Numbered co-agent fields
(`Agent_Name`, `Agent_Name_2`, …) — first agent through Step 14, full roster to
`raw_data.rt3_agents`. `Kitchens` is an underscore-token list (`_gas hob_, …`,
unique to RT3) parsed into `raw_data.rt3_kitchen_fittings`. `Views`/`Security`/
`Balcony`/`Patio`/`Garden` are comma-separated free-text tag lists folded into
`features`. Hyphenated `Type` taxonomy (`Commercial - Offices` → Office, etc.;
`Guest House`/`Unclassified` quarantine). `GPS` zero sentinel is
`"0.00000000,0.00000000"`. Photos hotlinked. `RT3_FEED_BASE_URL` (optional,
override only) is in `.env.example` and `src/server/env.ts`. See
`rt3/MAPPING_NOTES.md` and [`importers/README.md`](importers/README.md).

### Re-hosted listing media

`importers/src/iol_importers/media/` — a shared, feed-agnostic layer that
downloads a listing's photos, validates them by magic bytes, content-addresses
them under `data/media/` and records `listing_media` rows with site-relative
URLs. Built for Entegral (whose terms forbid hotlinking their images) as the
first consumer. The Next.js route handler `src/app/media/[...path]/route.ts`
serves the files from `MEDIA_ROOT_DIR` (default `<repo>/data/media`) with
traversal + extension guards and an immutable cache. `data/` is git- and
Docker-ignored, so a container needs a volume mounted at `data/media` — see
[Not yet implemented](#not-yet-implemented).

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
- The `importers/` subproject has its own checks (`uv run --project importers
ruff check .` and `uv run --project importers pytest` — offline, no DB). Its
  `pytest -m dbtest` suite is opt-in and needs `TEST_DATABASE_URL`.

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
- **A persistent volume for re-hosted listing media.** The Entegral importer
  writes downloaded photos to `data/media/` and `src/app/media/[...path]/route.ts`
  serves them from `MEDIA_ROOT_DIR` (default `<repo>/data/media`). `data/` is
  excluded from the image, so a container must mount a volume there (and share it
  between the importer job and the web service) — not wired.
- **Feed importer scheduling.** No cron/CronJob/EventBridge wiring for
  `p24-suburbs`, `propdata-import`, `propctrl-import`, `remax-import`,
  `entegral-import` (Entegral needs ≤ 24 h; run every 12 h),
  `propertyengine-import` (nightly; schedule unconfirmed with PropertyEngine),
  `fusion-import` (poll every ~15 min, or drive it from the notification webhook
  below), `allsa-import` (nightly per agency; full resend), `myroof-import`
  (nightly per franchise; full resend), `propertypost-import` (nightly per agency;
  full resend), `rt3-import` (nightly per agency, every configured province; full
  resend) or `iol-expire-listings`. Each command's docstring carries the intended
  cadence.
- **AllSA / MyRoof / PropertyPost / RT3 `feed_sources` rows.** Each AllSA agency
  (`code='allsa-<agencyid>'`, `auth_config->>'agency_id'`), each MyRoof franchise
  (`code='myroof-<franchise>'`, `auth_config->>'token'`), each PropertyPost agency
  (`code='propertypost-<agency>'`, full feed URL in `base_url`) and each RT3
  agency (`code='rt3-<agency>'`, province URL tokens in
  `auth_config->>'provinces'`) needs a seeded `feed_sources` row; feed sources
  are configuration and are never created by an import run. See
  `importers/src/iol_importers/{allsa,myroof,propertypost,rt3}/MAPPING_NOTES.md`.
- **Fusion `NotifyChangesAvailable` webhook.** The Fusion adapter implements the
  polling side (`RequestSnapshot` / `GetChanges`) only. Fusion can also call
  **into** us to signal "the queue has data" — an inbound endpoint that verifies
  the request's SecurityToken, replies `<RequestCompleted/>` within a minute, and
  does not itself call `GetChanges`. Not built.
- **Canonical `developments` sync for Fusion.** `<Development>` events are kept
  in `data/fusion/developments.json` + `raw_data`; `listings.development_id` is
  left NULL. Persisting a canonical `developments` row per Fusion development
  needs a `004` migration (`development_vendor_ids` + a soft-delete state on that
  table). See `importers/src/iol_importers/fusion/MAPPING_NOTES.md`.
- **The PropertyEngine feed URL.** `PROPERTYENGINE_FEED_URL` is blank — the
  Gumtree Pro schema doc specifies the file format only, so the hosting URL,
  whether it needs authentication, the pull schedule, and one-agency vs
  multi-agency scope all still need to come from PropertyEngine directly. The
  adapter runs today against a local file (`propertyengine-import --file …`);
  `propertyengine/MAPPING_NOTES.md` lists what is outstanding.
- **Lead / enquiry emails, with the Entegral copy rule.** No email-sending code
  exists. When enquiry notifications are built, an enquiry on an
  **Entegral-sourced** listing must be emailed to the listing's agent(s) **and
  copied to `support@entegral.net`** for Entegral's CRM, and Entegral-sourced
  listing/lead data must not be sold or handed to any third party. See
  `importers/src/iol_importers/entegral/MAPPING_NOTES.md`.

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
| `db/migrations/`               | —                | Reviewed DDL a maintainer applies by hand in DataGrip. Not run by the app or CI.                                               |
| `importers/`                   | —                | Python seed-data importers (uv + psycopg 3). Self-contained; see `importers/README.md`.                                        |
| `data/`                        | —                | Git-ignored. Timestamped feed downloads written by `pnpm run seed:suburbs:download`.                                           |

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
