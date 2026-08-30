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

## Feed infrastructure (`iol_importers.feeds`)

Shared scaffolding for the vendor feed importers still to be written
(`canonical-database-design.md` Domain 6). No vendor-specific parsing — just the
run/error bookkeeping every importer needs:

```python
from iol_importers.feeds import import_run

with import_run("allsa", file_reference=path.name) as run:
    for record in records:
        run.seen()
        try:
            ...                       # vendor parsing + upsert (importer's own connection)
            run.inserted()
        except ValidationError as exc:
            run.record_error(
                vendor_listing_id=record.get("id"),
                error_type="validation",
                error_message=str(exc),
                raw_payload=record,     # the untransformed payload
            )
```

- Opens one `import_jobs` row (`status='Running'`, `started_at`) and closes it:
  `Success` (no failures), `PartialSuccess` (some `record_error` calls), or
  `Failed` (the block raised — `error_message` set, exception re-raised).
- `record_error` writes one `import_errors` row and does **not** raise, so one bad
  record never stops the run. `raw_payload` is stored exactly as received.
- Tracking uses its own autocommit connection, so a rollback or crash in the
  importer's data transaction still leaves a closed job row — never one stuck at
  `Running`.
- Prerequisite: apply `../db/migrations/002_feed_infrastructure.sql` in DataGrip,
  then `pnpm db:pull`. `import_run` refuses to start until `feed_sources.ttl_days`
  and `import_jobs.records_skipped` / `error_message` exist.

Proof:

```sh
TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.feeds.demo
```

builds the Domain 6 tables in a throwaway schema, runs one `PartialSuccess` and
one `Failed` run, and prints the resulting rows.

## Core listing importer (`iol_importers.listings`)

Turns already-parsed vendor listing records (plain dicts — a feed-format adapter
is a later task) into `listings` rows (`canonical-database-design.md` Domain 4).

```python
from iol_importers.listings import import_listings

counts = import_listings(records, feed_source_code="allsa", file_reference=path.name)
```

Per record: `vendor_listing_id` + `title` required (else `validation`); scalars
coerced (junk → `parse`); then resolution —

| Ref | How it resolves |
| --- | --- |
| `listing_type` | normalised in-importer to the `('Sale','Rental','Unknown')` enum — `For Sale` / `4 Rent` / `TO LET` variants included |
| `property_type_id` | `property_type_vendor_mappings (feed_source_id, vendor_value)` → on a `property_types.name` hit the mapping row is written; a true miss is a `mapping` error |
| `suburb_id` | exact `suburbs.name`, then `alternate_names`; unresolved → **NULL, the listing still imports** |
| `agency_id` / `agent_id` | `agency_vendor_ids` / `agent_vendor_ids` keyed on `(feed_source_id, vendor_id)`; a new canonical agency/agent is created only when no mapping exists |

The listing is upserted on `UNIQUE (feed_source_id, vendor_listing_id)` — the same
key always resolves to an update, never a duplicate. Unpromoted vendor fields go
verbatim into `raw_data`. Price-history rows and `expires_at` are written by the
database triggers (`trg_listings_log_price_change` reads `ttl_days`, stamps the
job id from `app.current_import_job`); the importer only sets `price` and
`last_seen_at`.

A failed record is written to `import_errors` with the right `error_type`, counted
in `records_failed`, and the batch continues.

- Prerequisite: apply `../db/migrations/001`, `002`, then `003_listings_importer.sql`
  in DataGrip, then `pnpm db:pull`. The importer refuses to start until
  `property_type_vendor_mappings` exists, `listings.suburb_id` is nullable, and
  `suburbs.alternate_names` exists.

Proof:

```sh
TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.listings.demo
```

builds the Domain 4 tables in a throwaway schema, imports a batch, re-imports it
unchanged, then re-imports with one price dropped — printing the counts and the
single price-history row the change produces.

## Listing-expiry sweep (`iol_importers.lifecycle`)

The counterpart to the importer's `last_seen_at` refresh — the expiry-first
lifecycle. One atomic statement:

```sql
UPDATE listings SET status = 'Expired', expired_at = now()
WHERE status = 'Active' AND expires_at < now();
```

It touches only `status` and `expired_at` (`updated_at` bumps via the existing
trigger), never deletes, never writes `expires_at`. Idempotent — the
`status = 'Active'` filter means a second run changes zero rows. It reads live
`expires_at`, so a listing whose `expires_at` an import run just refreshed is
never expired.

Needs no migration — `listing_status` already has `Expired` and `listings` already
has `expired_at`.

```sh
uv run --project importers iol-expire-listings            # run the sweep
uv run --project importers iol-expire-listings --dry-run  # report only, no writes

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.lifecycle.demo   # before/after by status
```

**Scheduling** (nothing in this repo wires it — see the root README's "Not yet
implemented"). Intended cadence: nightly, after the feed imports refresh
`expires_at`.

```cron
15 2 * * *  cd /srv/iol-property-plus && \
    uv run --project importers iol-expire-listings >> /var/log/iol/expire.log 2>&1
```

Equivalents: a GitLab scheduled pipeline running the same command; a Kubernetes
`CronJob` with `schedule: "15 2 * * *"`; an ECS scheduled task via an EventBridge
rule.

## Propdata feed adapter (`iol_importers.propdata`)

The first real vendor feed. Pulls residential / commercial / holiday / project
listings from the Propdata API and feeds each record through the core listing
importer, tagged with `vendor_listing_type` so property-type / listing-type
mapping branches per category.

**Auth / renewal flow:**

- **Login** — `GET <PROP_DATA_API_LOGIN_URL>` with `Authorization: Basic
  base64(user:pass)` → `{ clients: [ { site: { domain }, token }, … ] }`. One
  bearer token **per client** (the test account has 138). The adapter picks the
  client whose `site.domain` matches `PROP_DATA_API_SITE`.
- **Renew** — `GET https://api-gw.propdata.net/users/api/v1/renew-token/` with
  `Authorization: Bearer <token>`; the **new token comes back in the `token`
  response header**. A run renews the stored token instead of re-doing Basic
  auth; it falls back to Basic login only if renewal fails.
- The token is held in memory and persisted (mode 0600) to
  `data/propdata/token-<site>.json` (git-ignored). It is never logged and never
  written to `import_errors`.
- Pagination: DRF `{ count, next, previous, results }`; `next` is followed to the
  end before a category's import job closes.

**Credentials** — set in `.env.local` (never committed; `.env.example` carries
empty placeholders):

```ini
PROP_DATA_API_USERNAME=...
PROP_DATA_API_PASSWORD=...
PROP_DATA_API_LOGIN_URL=https://api-gw.propdata.net/users/public-api/login/
```

**Run:**

```sh
PROP_DATA_API_SITE=harcourts.co.za \
    uv run --project importers propdata-import --page-limit 1

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.propdata.demo
```

Field mapping covers only what was verified against real API responses;
everything uncertain (coordinates, image URLs, `features`, commercial rental
price semantics, holiday) is left unmapped and recorded in
[`propdata/MAPPING_NOTES.md`](src/iol_importers/propdata/MAPPING_NOTES.md), not
guessed.

`pytest -m live` (opt-in, needs the credentials + `PROP_DATA_API_SITE`) exercises
a real login → renew → one page per category.

## Development

```sh
uv run --project importers ruff check .
uv run --project importers pytest                                  # no DB, no network
TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers pytest -m dbtest                    # opt-in
uv run --project importers pytest -m live                          # opt-in, real Propdata API
```

The `dbtest` suite leaves the target database untouched: the `p24-suburbs` tests
create their tables inside one transaction and roll back; the `feeds` and
`listings` tests use a dedicated `*_scratch_<pid>` schema dropped `CASCADE` at
teardown (they can't roll back — the point of the scaffolding is that rows
commit). Point `TEST_DATABASE_URL` at a scratch database, never the production
one.
