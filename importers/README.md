# importers/

Seed-data importers for `iol-property-plus`. Self-contained Python subproject —
the main app is TypeScript, and there was no prior Python importer to match, so
the conventions here are set fresh:

| Concern | Choice |
| --- | --- |
| Dependency manager | [uv](https://docs.astral.sh/uv/) (`uv.lock` committed) |
| Database driver | `psycopg` 3 — raw SQL, no ORM (the DataGrip-owned schema stays authoritative) |
| Config | `DATABASE_URL` from the environment, else the repo-root `.env.local`, else `postgresql://localhost:5432/iol_property_plus` |
| Tests | `pytest`; database tests are marked `dbtest` and skipped unless `TEST_DATABASE_URL` is set |
| Lint | `ruff` |

## Property24 suburb feed (`p24-suburbs`)

Seeds `provinces`, `cities` and `suburbs` (canonical-database-design.md Domain 1)
from Property24's public suburb CSV. **South Africa only** — every other country
in the feed is counted for visibility and dropped before any database work.

### Prerequisite

Apply `../db/migrations/001_suburbs_property24_columns.sql` in DataGrip, then run
`pnpm db:pull` from the repo root. The importer refuses to start until `suburbs`
has `extension`, `external_id` and `alternate_names`.

### Commands

```sh
uv sync --project importers                          # once

uv run --project importers p24-suburbs download       # -> data/property24/suburbs-<UTC>.csv
uv run --project importers p24-suburbs load           # parse newest download, upsert SA rows

# or via the repo-root passthroughs
pnpm run seed:suburbs:download
pnpm run seed:suburbs
```

`load` flags: `--file PATH` (default: newest download), `--dry-run` (resolve and
diff, then roll back), `--allow-count-drift` (proceed past the ~1% SA row-count
guard).

`download` is the only code path that makes a network request. `load` never
downloads and re-runs are idempotent — it upserts on Property24's `Id`
(`external_id`).

## Development

```sh
uv run --project importers ruff check .
uv run --project importers pytest                                  # no DB, no network
TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers pytest -m dbtest                    # opt-in
```

The `dbtest` suite creates its own tables inside one transaction and rolls back,
so it leaves the target database untouched. Point `TEST_DATABASE_URL` at a
scratch database, never the production one.
