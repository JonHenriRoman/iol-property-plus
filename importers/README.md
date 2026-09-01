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

## PropertyEngine feed adapter (`iol_importers.propertyengine`)

The fifth real vendor feed. PropertyEngine syndicates listings to us using
**Gumtree Pro's "Real Estate Standard Template Feed" v1.0.1** — Gumtree's own
prescribed outbound schema, which PropertyEngine implements. The schema doc
(`~/Documents/setup-guides/2RealEstate_StandardTemplate_GumtreePro (1) (2).pdf`)
specifies the **file format only** — never a URL, an auth scheme, or a schedule.

**Format — both, auto-detected.** Root is `{ Listings: { Property: [ … ] } }`. The
doc says JSON; the only PropertyEngine feed anyone has observed (sibling repo
`iol-property/packs/propertyengine`, 1084 live listings) is **XML** with the same
field names, just lowercased in places (`status`, `agent`, `email`, `CityTown`,
`AgentId`). `decode.py` sniffs the first non-whitespace byte and normalises both
into one nested-dict shape with case-insensitive, alias-tolerant field lookup.

**`Location` → suburb.** Appendix A is a `LocationID → SA -> Province -> [Area ->]
Locality` gazetteer with a lat/long centroid, transcribed once into
`propertyengine/locations.csv` (verified: unique ids, the nine SA provinces,
coordinates inside the SA bounding box). It is **not** suburb-level in general and
has no link to our Property24-derived `suburbs` ids. When `Location` is present,
its locality name is the suburb candidate (resolves for metro suburb rows, lands
`suburb_id` NULL for city rows — the listing still imports), and its
province/area/centroid go into `raw_data`. When `Location` is absent, the
documented free-text `Suburb` / `City`(`CityTown`) / `Province` are used. In the
observed feed, `Location` was never populated.

**`Type` → property type.** All 41 Appendix B values are mapped explicitly in
`map.py::_PROPERTY_TYPE`; nothing in-vocabulary errors. A `Type` **outside**
Appendix B is quarantined (`error_type='validation'`), never defaulted.

**Validation, two tiers.** `validate.py` rejects a record (`error_type='validation'`)
on a value breach — bad date format, malformed email, a space in `AgentPhone`,
an unknown `Type` or `Status`, no geography at all. The doc's Pascal-case /
no-underscore **tag-name** conventions are counted per run and logged, never
rejected — the real feed sends lowercase tags and rejecting on that would
quarantine 100% of it.

**Other semantics.** `Status` (For Sale / To Let / Holiday) is the market type,
not a lifecycle state — it maps to `listing_type` (`Holiday` → `Rental`; there is
no Holiday enum value). `Price == 0` means "Contact for Price" per the doc
(`price` NULL, `price_on_application` true); a missing `Price` tag is not `0`.
`Bedrooms` is *removed* for a studio, so its absence stays `None`. `Office` maps
onto `agencies` — there is no agency level above it. Photos are hotlinked
(`listing_media` rows), not re-hosted.

**Config** — `.env.local` (empty placeholders in `.env.example`; optional entries
in `src/server/env.ts`):

```ini
PROPERTYENGINE_FEED_URL=            # still pending from PropertyEngine
PROPERTYENGINE_FEED_AUTH_TOKEN=     # optional ("Authorization may be implemented")
PROPERTYENGINE_FEED_AUTH_SCHEME=    # bearer (default) | basic
```

**Run:**

```sh
# until the real URL lands, run against a local feed file:
uv run --project importers propertyengine-import --file data/propertyengine/feed.xml --dry-run
uv run --project importers propertyengine-import --file data/propertyengine/feed.xml

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.propertyengine.demo
```

Field mapping, judgement calls, and the full list of what still needs to come
from PropertyEngine directly (the URL, whether auth is enabled, the pull
schedule, one-agency vs multi-agency scope) are in
[`propertyengine/MAPPING_NOTES.md`](src/iol_importers/propertyengine/MAPPING_NOTES.md).
`pytest -m live` (opt-in) fetches the real feed and checks shapes only — it skips
until `PROPERTYENGINE_FEED_URL` is set.

## Fusion FeedStore feed adapter (`iol_importers.fusion`)

Private Property SA's **event-sourced XML sync** — not a REST pull. Four POST
methods on `…/v1/sync/` (`RequestSnapshot`, `GetChanges`, `RequestRollback`,
`GetClientState`), each signed with a **fresh** SecurityToken in the query string
(`digest = base64(sha1(f"{timeStamp}*{password}*{salt}"))`, `timeStamp` =
`YYYY-MM-DD-HH-MM` UTC — tokens are never reused). `GetChanges` also sends a
`commitToken=` form body.

**The drain loop:**

- First run for a client (no `data/fusion/state.json`, no snapshot in progress) →
  `RequestSnapshot`, then drain `GetChanges` (no token on the first call).
- `<BeginSnapshot>` … `<Snapshot>` … `<EndSnapshot/>` **may span many
  `GetChanges` calls** — the adapter accumulates across batches.
- **commitToken**: send the previous token to acknowledge a batch and get the
  next; **omit** it to replay the last. The token is persisted **only after a
  batch is fully applied**, so a crash replays it — every event is an idempotent
  upsert / soft-delete.
- `<Exception>` handling: `HousekeepingInProgress` / `ServiceOffline` /
  `InternalError` / `SecurityTokenExpired` → back off and retry (client);
  `InvalidCommitToken` → restart from the token the error supplies;
  `CommitTokenExpired` → restart with a blank token.

**Object routing:**

- `<Listing>` → `import_listings` (upsert on the Fusion `@id`, **never**
  `fusionRef`); `<Delete><ListingRef>` → `lifecycle.withdraw_listings`
  (`status='Withdrawn'`).
- `<Office>` → `agencies` + `agency_vendor_ids`; `<Agent>` → `agents` +
  `agent_vendor_ids`; `<Delete>` → `status='Inactive'` (`fusion/reference.py`).
- `<AreaTree>` → `data/fusion/area_tree.json`, a `suburbId` → name crosswalk fed
  to the existing `resolve_suburb` (**no parallel geography table**). Unresolved
  → `suburb_id` NULL; a post-`EndSnapshot` pass backfills listings whose AreaTree
  node arrived in a later batch.
- `<Development>` → **deferred** to `data/fusion/developments.json` + `raw_data`;
  canonical `developments` sync needs a `004` migration (no feed key / no
  soft-delete state on that table).

Photos are **hotlinked** (operator's choice — `primary_image_url` + `listing_media`
rows are Fusion CDN URLs). `NotifyChangesAvailable` (Fusion calling into us) is
out of scope. See
[`fusion/MAPPING_NOTES.md`](src/iol_importers/fusion/MAPPING_NOTES.md).

**Credentials** — `.env.local` (empty placeholders in `.env.example`):

```ini
FUSION_CLIENT_ID=...
FUSION_PASSWORD=...
FUSION_API_BASE_URL=        # blank = production; set the doc's QA host to test
```

```sh
uv run --project importers fusion-import                 # first run: snapshot, then drain
uv run --project importers fusion-import --state         # local + remote GetClientState, no changes
uv run --project importers fusion-import --dry-run --max-batches 1

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.fusion.demo
```

`pytest -m live` (opt-in, needs `FUSION_*`) does a real `GetClientState` and one
non-acknowledging `GetChanges` — it never moves the real cursor and never issues
`RequestSnapshot` against a non-QA host.

**Scheduling** (not wired — see the root README's "Not yet implemented"): poll
every ~15 minutes, or drive it from the `NotifyChangesAvailable` webhook once
that half is built.

## AllSA Property feed adapter (`iol_importers.allsa`)

The public, unauthenticated `iol.ashx` XML feed — one HTTP GET returns an agency's
**whole book** (`<Listings><Property>…</Property></Listings>`, flat, no office
grouping). A full resend on every pull, same shape as PropertyEngine: parse, map,
`import_listings`, then reconcile absences with `lifecycle.withdraw_missing`
(gated on a non-empty id set — an empty `<Listings/>` withdraws nothing).

**One `feed_sources` row per agency.** The `agencyid` query parameter is *not* in
the source tree — it lives on the row:

```sql
INSERT INTO feed_sources (code, name, vendor_name, format, base_url, auth_config)
VALUES ('allsa-10173', 'National Real Estate', 'AllSA Property', 'XML',
        'https://www.allsaproperty.co.za/feeds/iol.ashx',
        '{"agency_id": "10173"}');
```

`vendor_listing_id` is the bare `Reference`, keyed by `feed_source_id` so a
cross-agency collision cannot happen.

**Object routing:**

- `<Property>` → `import_listings`. `Heading` is the title; **`Title` is tenure**
  (`Freehold` / `Sectional Title`) and goes to `raw_data.allsa_tenure`. `Price`
  `0.00` → price-on-application.
- **`BranchId`** → `agencies` + `agency_vendor_ids`; `lower(Agent_Email)` →
  `agents` + `agent_vendor_ids` (`allsa/reference.py`). One agency's feed spans
  several branches (the real 10173 feed has four); `Agency_Location` is the
  listing's servicing town, not the office, and stays in `raw_data`.
- Photos **hotlinked** — `primary_image_url` + `listing_media` rows on the AllSA
  CDN. No re-hosting requirement.

**`<Features>` parsing (`allsa/features.py`).** A free-form bag whose child set
varies per listing (28 distinct tags observed, illustrative not exhaustive). The
parser iterates the actual children against a registry: counts → typed columns
(`Carports + Parking` → `parking_spaces`), `Erf_Size`/`Floor_Size` → m² columns,
`Land_Size` → m² via a hectares-vs-m² heuristic (backfills `erf_size` only when
absent and it fits `numeric(10,2)`), `Yes` flags → `listings.features` labels,
**unknown tags** → `raw_data.allsa_features_extra` + a per-run tally. `<Features>`
children repeat within one `<Property>` in the real feed (one listing carries
each tag 1852×) — first occurrence wins, drops are counted.

```sh
uv run --project importers allsa-import --feed-source allsa-10173
uv run --project importers allsa-import --agency-id 10173 --dry-run   # skips the DB lookup
uv run --project importers allsa-import --feed-source allsa-10173 --file feed.xml

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.allsa.demo
```

`ALLSA_LIVE_AGENCY_ID=10173 pytest -m live -k allsa` does a real fetch and maps
every listing — no database writes. See
[`allsa/MAPPING_NOTES.md`](src/iol_importers/allsa/MAPPING_NOTES.md).

**Scheduling** (not wired — see the root README's "Not yet implemented"): a
nightly pull per agency; the feed is a full resend (~3.5 MB), not a short poll.

## MyRoof feed adapter (`iol_importers.myroof`)

The per-franchise feed at `https://rat.myroof.co.za/{token}` — one HTTP GET
returns a franchise's whole book (~7.6 MB / ~3,857 listings) as the bracketed
key-value text format shared by RT3, MyRoof and PropertyPost. **Built on the
shared parser `iol_importers.bracket_kv`** — it is not reimplemented. Full resend,
no delta, no delete signal → parse, map, `import_listings`, then
`lifecycle.withdraw_missing` (which refuses an empty seen set, so a broken fetch
cannot withdraw the book).

**One `feed_sources` row per franchise.** The opaque `{token}` path segment is the
entire credential — it lives on the row, never in the source tree, an env var, a
log line, or the run result:

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
VALUES ('myroof-acme', 'Acme Realty (MyRoof)', 'MyRoof',
        'https://rat.myroof.co.za', '{"token": "<opaque feed token>"}');
```

**Vendor specifics** (from a real 3,857-record run):

- the whole feed is **bank-repossessed stock** — every record gets a synthetic
  `Repossession` feature, and `Agent_Name` is a lender/program label ("Standard
  Bank Repossessed", …) used as the agent's name (also kept in
  `raw_data.myroof_agent_program`); `Email` is the stable per-agent id;
- `Description` carries literal `<p>` tags as paragraph breaks — converted to
  newlines, entities unescaped, never passed through raw;
- `GPS` is one `"lat,lng"` string with a bare-comma "not supplied" sentinel →
  `latitude`/`longitude` NULL;
- `Type` → seeded `property_types` (`Complex` → Townhouse, `Plot` → Vacant Land,
  `Freehold Residence` → House, …); `Guest House` is left unmapped and quarantines
  the record rather than guessing;
- single brand — every record is `Branch_Name` `MyRoof.co.za` / `Branch_ID` `1`;
- every unlisted key is captured under `raw_data.myroof_<Key>` (a list when it
  repeats, e.g. `Video_URL`); `Kitchens` is a plain count here (not RT3's list).

Photos hotlinked (`primary_image_url` + `listing_media`); MyRoof imposes no
re-hosting term.

```sh
uv run --project importers myroof-import --feed-source myroof-acme
uv run --project importers myroof-import --token <token> --dry-run   # skips the DB lookup
uv run --project importers myroof-import --feed-source myroof-acme --file feed.txt

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.myroof.demo
```

`MYROOF_LIVE_TOKEN=<token> pytest -m live -k myroof` does a real fetch and maps
every record — no database writes. See
[`myroof/MAPPING_NOTES.md`](src/iol_importers/myroof/MAPPING_NOTES.md).

**Scheduling** (not wired — see the root README's "Not yet implemented"): a
nightly pull per franchise; the feed is a full resend, not a short poll.

## PropertyPost feed adapter (`iol_importers.propertypost`)

One static per-agency URL (e.g. `http://lms.propertypost.co.za/BstProperties.txt`,
redirecting plain HTTP to HTTPS) — a plain GET with **no auth of any kind**,
returning the agency's whole book (~640 KB / ~200 listings) as the same bracketed
key-value text format. The last of the three bracket-KV vendors and the third
adapter **built on the shared parser `iol_importers.bracket_kv`**. Full resend →
parse, map, `import_listings`, then `lifecycle.withdraw_missing`.

**One `feed_sources` row per agency.** There is no credential, so the per-agency
value is the full URL itself (its filename identifies the agency):

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url)
VALUES ('propertypost-bst', 'BST Properties (PropertyPost)', 'PropertyPost',
        'http://lms.propertypost.co.za/BstProperties.txt');
```

**Vendor specifics** (from a real 197-record fetch):

- **one file carries both `For Sale` and `To Let`** — there is no separate rental
  endpoint; the run reports the split;
- the sampled URL is **one independent agency** (`Branch_ID` `39350` on every
  record), but agency identity is resolved **per record** from
  `Branch_ID`/`Branch_Name`, so a multi-branch file needs no code change and the
  distinct-branch count is on every run's result;
- `Beds`/`Baths` duplicate `Bedrooms`/`Bathrooms` — coalesced (`Bedrooms`/
  `Bathrooms` win, a blank side falls back), a genuine numeric disagreement
  recorded in `raw_data` and tallied, never silently overwritten or double-counted;
- `GPS` is simply **absent** from a record with no coordinates — no sentinel;
- the 14 amenity keys (`Fence` … `Kitchens`) are pure `YES` booleans →
  feature labels (`Kitchens: YES` is a flag here, not MyRoof's count);
- `Type` → seeded `property_types` (`Stand` → Vacant Land, `Smallholding` → Farm,
  `Apartment Or Flat`/`Flat` → Apartment); every live value maps;
- `Carports` → `parking_spaces`, `Verified` → `vendor_updated_at`, a missing
  `Heading` → a synthesized title (first line of `Description`, else
  `"{property_type} in {suburb}"`), tallied;
- `Features_Description` is unstructured prose with an embedded
  `Label - Value - Detail` triple format — kept **verbatim** in `raw_data`, never
  parsed; `Admin_ID` is a constant company contact kept as
  `raw_data.propertypost_admin_email`, distinct from the per-listing agent;
- every other unlisted key is captured under `raw_data.propertypost_<Key>`;
- the live feed has a handful of byte-identical duplicate `Reference` records and
  a trailing run of bare `[[Listing_Start]]` padding — both are harmless (the
  upsert makes a duplicate a no-op; the parser drops the padding).

Photos hotlinked (`primary_image_url` + `listing_media`).

```sh
uv run --project importers propertypost-import --feed-source propertypost-bst
uv run --project importers propertypost-import \
    --feed-url http://lms.propertypost.co.za/BstProperties.txt --dry-run
uv run --project importers propertypost-import --feed-source propertypost-bst --file feed.txt

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.propertypost.demo
```

`PROPERTYPOST_LIVE_FEED_URL=<url> pytest -m live -k propertypost` does a real fetch
and maps every record — no database writes. See
[`propertypost/MAPPING_NOTES.md`](src/iol_importers/propertypost/MAPPING_NOTES.md).

**Scheduling** (not wired — see the root README's "Not yet implemented"): a
nightly pull per agency; the feed is a full resend, not a short poll.

## RT3 (Rawson) feed adapter (`iol_importers.rt3`)

One bracket-KV file per province at
`https://webservices.rawsonproperties.co.za/iol-{Province}.txt` — a plain public
GET with **no auth of any kind**, ~17 MB per province. The last of the three
bracket-KV vendors on the shared `iol_importers.bracket_kv` parser.

**One `feed_sources` row per agency, with the province list.** RT3 is a single
brand ("Rawson Properties"); what is per-agency is *which province files* it
publishes — a JSON array of URL tokens (the exact `{Province}` segment):

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
VALUES ('rt3-rawson', 'Rawson Properties (RT3)', 'RT3',
        'https://webservices.rawsonproperties.co.za',
        '{"provinces": ["Western_Cape", "Gauteng", "KwaZulu-Natal"]}');
```

Run shape: **every configured province file is fetched up front** (any fetch
failure aborts the whole run before anything is imported or reconciled) → all
provinces imported in one job → photos hotlinked → **per-province reconcile** via
`withdraw_missing(code, seen, raw_scope=("rt3_province", province))`, so a broken
or missing province never withdraws another province's listings.

**Vendor specifics** (from a real 4,137-record Gauteng run):

- single brand — `Branch_ID` / `Branch_Name` are the per-listing office identity,
  used directly as the agency; `"Rawson Properties"` → `raw_data.rt3_brand`;
- **numbered co-agent fields** — `Agent_Name` / `Cell_No` / `Email`, then
  `Agent_Name_2` … for an arbitrary number more. The first agent resolves through
  Step 14; the full ordered roster → `raw_data.rt3_agents` (+ `rt3_co_agent_count`).
  Handles zero / one / many / gappy suffix sets;
- **`Kitchens` is an underscore-token list** (`_gas hob_, _granite tops_`) —
  unique to RT3 (MyRoof / PropertyPost use it as a plain count/flag). Parsed into
  `raw_data.rt3_kitchen_fittings`; not a feature, not a count;
- **`Views` / `Security` / `Balcony` / `Patio` / `Garden` are comma-separated
  free-text tag lists** — every token folded into `features` (plus `Pool` /
  `Alarm` / `Laundry` / `Staff_Accomm` / `Ensuites` as boolean labels);
- `Study` / `Family_Rooms` / `Reception_Rooms` / `Levels` are numeric counts →
  `raw_data`;
- hyphenated `Type` taxonomy — `Commercial - Offices` → Office,
  `Commercial - Factory`/`Warehouse` → Industrial, `Commercial - Vacant Land` →
  Vacant Land, the rest of `Commercial - *` → Commercial; `Guest House` /
  `Unclassified` quarantine rather than guess;
- `GPS` zero sentinel is `"0.00000000,0.00000000"` (also `"0,0"` / both-zero);
- `Status` (`For Sale` / `To Let`) is the listing type; `Listed` is a
  `YYYY-MM-DD` publish date.

Photos hotlinked (`primary_image_url` + `listing_media`).

```sh
uv run --project importers rt3-import --feed-source rt3-rawson
uv run --project importers rt3-import --province Gauteng --province Western_Cape --dry-run
uv run --project importers rt3-import --file Gauteng=iol-Gauteng.txt --file Western_Cape=iol-Western_Cape.txt

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.rt3.demo
```

`RT3_LIVE_PROVINCE_URL=<url> pytest -m live -k rt3` does a real one-province fetch
and maps every record — no database writes. See
[`rt3/MAPPING_NOTES.md`](src/iol_importers/rt3/MAPPING_NOTES.md).

**Scheduling** (not wired — see the root README's "Not yet implemented"): a
nightly pull per agency, every configured province; the feed is a full resend,
not a short poll.

## Webbox feed adapter (`iol_importers.webbox`)

One XML file per site at
`{domain}/template/feeds,WebboxFeedForSite.vm/siteid/{siteid}/securitykey/{securitykey}/feed.xml`
— a plain GET where **the URL itself is the credential**. Stream-parsed with
stdlib `xml.etree.ElementTree.iterparse` (no lxml — the same "trusted vendor over
TLS" call AllSA / Fusion make, and `iterparse` covers the objective's stream-parse
ask). Full resend → parse, enrich agencies/agents, `import_listings`, hotlink
media, `withdraw_missing`.

**One `feed_sources` row per site.** The URL is the credential, so the per-site
values are the domain (`base_url`) and the `siteid` + `securitykey` pair
(`auth_config`) — never in the source tree, an env var, or a log line:

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
VALUES ('webbox-valuables', 'Valuables Properties (Webbox)', 'Webbox',
        'https://www.valuablesproperties.co.za',
        '{"siteid": "612", "securitykey": "<opaque key>"}');
```

**Outer structure** (confirmed from the sibling Go pack's real 21- and
411-property captures): `<agencies>` → `<agency>` (1+) → `<agency-details>` +
`<properties>` → `<property>[]`. The repeated `<property>` nests two levels inside
`<agency>`, so the parser carries each agency's `<agency-details>` context down
onto its flat property records. It also accepts a bare `<property>` root and a
consecutive stream — `outer_form` (`wrapped` / `bare-property` / `streamed`) is
reported on every run.

**Vendor specifics** (from the Go pack + the real 3-property sample):

- `listing-type` (`Sale` / `Rent`) is the listing type — no lifecycle field;
- **`price/currency` must be `ZAR`** (Step 14 has no per-listing currency column)
  — a non-ZAR listing is **rejected**; **`location/country` is validated, not
  hardcoded** — a non-`South Africa` listing is imported with `suburb_id` NULL
  and tallied;
- an empty `<amount/>` is a real price-on-application case;
- `<features>` is a free-form bag — `bedrooms` / `bathrooms` (decimal) /
  `garages` → columns, `taxes` → `rates_and_taxes`, unknown tags → `raw_data`;
- `land-size` / `property-size` carry a lowercase unit string (`meters_squared`,
  `hectares`) → unit-aware `erf_size` / `floor_size`;
- multiple `<agent>` — the first drives the FK, the full roster →
  `raw_data.webbox_agents`; rich agency/agent contact fields reach the canonical
  `agencies` / `agents` tables through `webbox/reference.py` (run before the
  import), keyed on `agency-details/id` and `agent-id`;
- `description` embeds `Availability:` / `Deposit R…` free text — left verbatim;
- **no date field of any kind** → `listed_at` NULL.

Photos hotlinked (`primary_image_url` + `listing_media`).

```sh
uv run --project importers webbox-import --feed-source webbox-valuables
uv run --project importers webbox-import \
    --base-url https://www.valuablesproperties.co.za --siteid 612 --securitykey <key> --dry-run
uv run --project importers webbox-import --feed-source webbox-valuables --file feed.xml

TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers python -m iol_importers.webbox.demo
```

`WEBBOX_LIVE_DOMAIN=… WEBBOX_LIVE_SITEID=… WEBBOX_LIVE_SECURITYKEY=… pytest -m live
-k webbox` does a real fetch, maps every property, and prints the confirmed
`outer_form` — no database writes. See
[`webbox/MAPPING_NOTES.md`](src/iol_importers/webbox/MAPPING_NOTES.md).

**Scheduling** (not wired — see the root README's "Not yet implemented"): a
nightly pull per site; the feed is a full resend, not a short poll.

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

## Dry-run wrapper (`iol_importers.dryrun`)

The web app's feed-operations UI (`/ops/feeds`) calls this to run a test import:

```sh
uv run --project importers python -m iol_importers.dryrun <vendor> <feed_sources.code> --json
```

It owns the `vendor -> adapter` dispatch table and normalises every adapter's
`run(dry_run=True)` result to one JSON shape (`ok`, `records_seen`,
`diagnostics`, `message`). It never writes: dry-run returns before any
`import_jobs` row is opened. A feed-side failure (unreachable feed, missing
`feed_sources` row, absent credentials) comes back as `{"ok": false, ...}`, not a
crash. `remax`, `propdata` and `propctrl` have no dry-run mode and return a
`supported: false` sentinel.

## Development

```sh
uv run --project importers ruff check .
uv run --project importers pytest                                  # no DB, no network
TEST_DATABASE_URL=postgresql://localhost:5432/postgres \
    uv run --project importers pytest -m dbtest                    # opt-in
uv run --project importers pytest -m live                          # opt-in, real Propdata / PropCtrl / RE/MAX / Entegral / PropertyEngine feeds
```

The `dbtest` suite leaves the target database untouched: the `p24-suburbs` tests
create their tables inside one transaction and roll back; the `feeds` and
`listings` tests use a dedicated `*_scratch_<pid>` schema dropped `CASCADE` at
teardown (they can't roll back — the point of the scaffolding is that rows
commit). Point `TEST_DATABASE_URL` at a scratch database, never the production
one.
