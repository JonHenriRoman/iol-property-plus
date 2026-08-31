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
            ...  # vendor parsing + upsert (importer's own connection)
            run.inserted()
        except ValidationError as exc:
            run.record_error(
                vendor_listing_id=record.get("id"),
                error_type="validation",
                error_message=str(exc),
                raw_payload=record,  # the untransformed payload
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

`iol_importers.lifecycle.withdraw_listings(feed_source_code, vendor_listing_ids)`
is the counterpart for feeds that send **explicit** deletions (RE/MAX's
`/lists_deleted`): one `UPDATE listings SET status = 'Withdrawn', expired_at =
now() WHERE … AND status <> 'Withdrawn'`. Never deletes a row, only touches
listings that exist, idempotent. Also no migration.

`iol_importers.lifecycle.withdraw_missing(feed_source_code, seen_vendor_listing_ids,
*, raw_scope=None)` is for feeds that send a full **snapshot** of a scope
(Entegral's per-office `officelistings`): it withdraws every non-withdrawn
listing in the scope — optionally narrowed by `raw_data ->> raw_scope[0] =
raw_scope[1]` — whose id is not in the snapshot. Refuses an empty `seen` set so
an empty snapshot can't withdraw everything. Same soft-delete, no migration.

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

## PropCtrl feed adapter (`iol_importers.propctrl`)

The second real vendor feed. PropCtrl is the agency CRM behind `iolproperty.co.za`
itself, exposed as **PropCtrl Listing Service v1** — an OpenAPI 3.0.4 service. The
contract was discovered from the spec, not assumed:

```sh
curl -s https://api.propctrl.com/index.html            # Swagger UI; names the spec URLs
curl -s https://api.propctrl.com/v1-listing/swagger.json
```

**Model — a delta feed, not a paginated one:**

- **Auth** — HTTP Basic on every request (`base64(username:password)`, or a blank
  username with an API key as the password). No token, nothing to renew.
  `GET /listing/v1/admin/echo-authenticated` is the credential probe.
- `GET /listing/v1/listings/changes?fromDate=<ISO-8601>` →
  `{ items: [ { id, changeType: New|Modified|Removed, … } ], nextFromDate }`.
  `nextFromDate` is the cursor for the next run.
- `GET /listing/v1/listings?listingIds=…` → full listings, **at most 10 ids per
  call**. `suburbs` / `agencies` / `branches` / `agents` are fetched by id too.

The adapter resumes from `data/propctrl/checkpoint.json` (git-ignored, mode 0600,
holds only `next_from_date`). `Removed` change items and any listing whose
`listingStatus` is not `Active` are skipped and counted — the importer has no
withdraw path; the `iol-expire-listings` sweep handles listings that stop being
refreshed.

**Read-only.** `PUT /listing/v1/listings/{listingId}` (the status write-back half
of the PropCtrl partner protocol) is deliberately not implemented.

**Credentials** — set in `.env.local` (never committed; `.env.example` carries
empty placeholders):

```ini
PROPCTRL_API_USERNAME=...
PROPCTRL_API_PASSWORD=...
PROPCTRL_API_BASE_URL=https://api.propctrl.com
```

**Run:**

```sh
uv run --project importers propctrl-import --from-date 2026-08-25T00:00:00Z --max-listings 100

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.propctrl.demo
```

Field mapping covers only what the spec documents and real responses confirm;
everything uncertain (`commercialInfo` / `farmInfo` detail, non-monthly pricing
bases, suburb disambiguation, `internalRemarks` — excluded by design) is recorded
in [`propctrl/MAPPING_NOTES.md`](src/iol_importers/propctrl/MAPPING_NOTES.md).
`pytest -m live` (opt-in) exercises a real echo → changes → one bounded batch.

## RE/MAX feed adapter (`iol_importers.remax`)

RE/MAX of Southern Africa — an AWS API Gateway deployment, so the auth is at the
**IAM layer**, not the application layer.

**Auth — both.** Every request is `POST` + JSON body, **AWS SigV4-signed**
(`service=execute-api`, `region=eu-west-1`; hand-rolled in
[`remax/signing.py`](src/iol_importers/remax/signing.py), stdlib only — no
`botocore`) **and** carries an `x-api-key` header (usage-plan key). SigV4 alone →
`403 Missing Authentication Token`; `x-api-key` alone → `403 Forbidden`.

**Envelope.** Responses are `{"Success": true, "data": "<JSON string>"}` — `data`
is decoded a second time.

**Three sync paths:**

- **full** (`--mode full`) — `/lists {agents:true}` → `/agents-page` per agent,
  following `properties.hasNextPage`. The only paginated path that returns the
  full listing shape (with `features`).
- **incremental** (default) — `/lists-pagenate {listings:true, start_date}`
  (resumes from `data/remax/checkpoint.json`), then `/listing {id}` per changed
  listing. **Deviation:** the doc says use `/lists` + `start_date`, but that
  endpoint returns HTTP 500 — `/lists-pagenate` is used instead.
- **deleted** (every run unless `--no-deleted`) — `/lists_deleted` →
  `lifecycle.withdraw_listings` (soft-delete: `status='Withdrawn'`, never a row
  removal).

`date_last_updated` is compared against `listings.last_updated_by_vendor_at`, so an
unchanged listing is **skipped**, not re-upserted. `504`s (Lambda cold starts) are
retried with backoff.

**Credentials** — `.env.local` (empty placeholders in `.env.example`):

```ini
REMAX_ACCESS_KEY=...
REMAX_SECRET_KEY=...
REMAX_API_KEY=...
REMAX_API_BASE_URL=https://ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com/feeds_default
```

(The objective names the AWS vars `REMAX_AWS_ACCESS_KEY_ID` /
`REMAX_AWS_SECRET_ACCESS_KEY`; the deployed `.env.local` uses `REMAX_ACCESS_KEY` /
`REMAX_SECRET_KEY` — the real env file wins, as with Propdata.)

```sh
uv run --project importers remax-import --mode incremental --max-pages 2
uv run --project importers remax-import --deleted-only

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.remax.demo
```

Mapping covers only what the live API confirms; deviations and unmapped fields
(`geo_location`/`address` always empty, `listing_state`, agent soft-delete,
`rental_details`, …) are in
[`remax/MAPPING_NOTES.md`](src/iol_importers/remax/MAPPING_NOTES.md).
`pytest -m live` (opt-in) exercises real signed calls to all four endpoints.

## Entegral feed adapter (`iol_importers.entegral`)

A **pull** feed — not the push-oriented Sync API in Entegral's public docs
(confirmed with Entegral directly, 2026-08-13). Two HTTP Basic-auth `GET`
endpoints on `sync.entegral.net`:

- `GET /api/officeslist` — the offices that opted into syndication to us, each
  with an `officereference`.
- `GET /api/listings?type=officelistings&ref={officereference}` — one office's
  **complete active** listing set, agent + office contact inline (a shape like
  the Sync API `CreateOrUpdateListing` object).

A run calls `officeslist` first, then `officelistings` once per office, and feeds
each office's listings through the core importer as its own `import_listings`
call.

**No deletions endpoint.** `officelistings` is a full snapshot, so a listing that
disappears is caught by **per-office reconciliation**:
`lifecycle.withdraw_missing` soft-deletes (`status='Withdrawn'`) every listing
scoped to that `officereference` — via `raw_data ->> 'entegral_office_reference'`
— whose id was absent from the response. Skipped entirely when an office's
response is empty or its import had a failure, so a transient empty response
never withdraws an office's book.

**Photos are re-hosted, not hotlinked.** Entegral's terms forbid hyperlinking
their images (and `next.config.ts` denies all remote image hosts). Every
`photos[].imgUrl` is downloaded, validated by magic bytes, content-addressed
under `data/media/entegral/…` by the shared [media store](#media-store), and
recorded in `listing_media` with a site-relative `/media/entegral/…` URL;
`primary_image_url` points at the first re-hosted asset. A source-URL index means
re-polls re-download nothing (`--refresh-media` forces it). One photo failing
never fails its listing.

**Agent + office name are required.** A listing missing either is recorded in
`import_errors` (`error_type='validation'`) and not imported — never a silent
import without attribution.

**Credentials** — `.env.local` (empty placeholders in `.env.example`):

```ini
ENTEGRAL_USERNAME=...
ENTEGRAL_PASSWORD=...
```

The client tries `https://sync.entegral.net` first and drops to the `http://`
URLs Entegral gave only if TLS is unreachable (logging a warning).

```sh
uv run --project importers entegral-import --max-offices 2 --max-listings 5
uv run --project importers entegral-import --dry-run
uv run --project importers entegral-import -o OFF123 --no-media

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.entegral.demo
```

**Scheduling** (not wired — see the root README's "Not yet implemented"). The
feed updates twice a day and Entegral requires a poll at least every 24 hours;
run it every 12 hours to catch both:

```cron
0 */12 * * *  cd /srv/iol-property-plus && \
    uv run --project importers entegral-import >> /var/log/iol/entegral.log 2>&1
```

Mapping, deviations, unmapped fields, and the **obligations that live outside
this importer** (lead emails to the agent **and** `support@entegral.net`; no
third-party data handoff; the open decision on a listing deep-link pattern) are
in [`entegral/MAPPING_NOTES.md`](src/iol_importers/entegral/MAPPING_NOTES.md).
`pytest -m live` (opt-in) exercises a real `officeslist` + one `officelistings` +
one photo download.

## Media store (`iol_importers.media`)

Shared, feed-agnostic photo re-hosting — Entegral is its first consumer; the
other feeds keep their hotlinked `primary_image_url` for now and can adopt it
later.

- `media.store.MediaStore` — a content-addressed directory tree
  (`<root>/<feed>/<sha[:2]>/<sha>.<ext>`, default root `data/media`). Identical
  bytes are stored once; a re-run produces the same URL.
- `media.sniff` — magic-byte type detection (JPEG/PNG/WebP/GIF) and header-only
  pixel dimensions, stdlib (no Pillow). The vendor `Content-Type` is not trusted.
- `media.fetch.fetch_and_store` — streamed download with a 15 MB cap, an
  allow-list check **after** sniffing, and a source-URL index so re-polls skip
  the HTTP fetch.
- `media.db.sync_listing_media` — upsert `listing_media` rows for a listing and
  prune the ones whose URL is no longer present (photo removed vendor-side).

Served to the browser by the Next.js route handler
`src/app/media/[...path]/route.ts`, reading from `MEDIA_ROOT_DIR` (default
`<repo>/data/media`) with path-traversal and extension guards and a one-year
immutable cache. Under Docker that directory needs a mounted volume — see the
root README's "Not yet implemented".

## Development

```sh
uv run --project importers ruff check .
uv run --project importers pytest                                  # no DB, no network
TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers pytest -m dbtest                    # opt-in
uv run --project importers pytest -m live                          # opt-in, real Propdata / PropCtrl / RE/MAX APIs
```

The `dbtest` suite leaves the target database untouched: the `p24-suburbs` tests
create their tables inside one transaction and roll back; the `feeds` and
`listings` tests use a dedicated `*_scratch_<pid>` schema dropped `CASCADE` at
teardown (they can't roll back — the point of the scaffolding is that rows
commit). Point `TEST_DATABASE_URL` at a scratch database, never the production
one.
