# Fusion FeedStore feed — mapping notes

## The protocol

Private Property SA's **event-sourced XML sync**, per
<https://privatepropertysa.gitlab.io/fusion-feedstore-api/docs/> (Revision 32).
Not a REST pull. Four POST methods on `…/v1/sync/`:

| Method | Purpose |
| --- | --- |
| `RequestSnapshot` | pause the change queue, re-send every object, then resume |
| `GetChanges` | the workhorse — up to 10 MB of `<Changes>` XML per call |
| `RequestRollback` | re-send the event history from a past time (≤ 7 days) |
| `GetClientState` | the current cursor, without consuming events |

Security-token params (`clientId`, `timeStamp`, `salt`, `digest`) go in the
**query string**; `GetChanges` / `RequestRollback` also send a form-urlencoded
body (`commitToken=` / `startTime=`). A **fresh** token is generated for every
call (and every retry) — `digest = base64(sha1(f"{timeStamp}*{password}*{salt}"))`,
`timeStamp` = `YYYY-MM-DD-HH-MM` UTC, `salt` = a random 64-bit int as a decimal
string. `security.py` is the pure implementation; the password lives only in the
client's private attribute and is never logged.

### The GetChanges loop

- First run for a client (no saved `commitToken` and no snapshot in progress):
  `RequestSnapshot`, then drain `GetChanges` (no token on the first call).
- `<BeginSnapshot types="…">` … `<Snapshot>` … `<EndSnapshot/>` **may span many
  `GetChanges` calls** — the adapter does not assume one call drains it.
- **commitToken**: send the previous token to *acknowledge* the last batch and
  get the next; **omit** it to *re-send the identical last batch*. The token is
  persisted to `data/fusion/state.json` **only after a batch is fully applied**,
  so a crash mid-batch replays it — and every event is an idempotent upsert /
  soft-delete, so the replay is harmless.
- A drained queue is `<Changes clientId="…"></Changes>` — no `commitToken`
  attribute.
- `<Exception type="…">` handling: `HousekeepingInProgress` → back off and retry
  (client, ~10 min); `ServiceOffline` / `InternalError` / `SecurityTokenExpired`
  → back off and retry (client); `InvalidCommitToken` → restart from the
  `commitToken` the error supplies (adapter); `CommitTokenExpired` → restart
  `GetChanges` with a blank token (adapter); `InvalidClientID` /
  `InvalidParameter` → raise.

`xml.etree.ElementTree` (stdlib) is used: it resolves no external entities and
does no I/O. The residual internal-entity-expansion risk is accepted for a
trusted vendor over TLS — `defusedxml` would be a belt-and-braces hardening.

### Base URL

`_DEFAULT_FUSION_BASE_URL` is the production host. Set `FUSION_API_BASE_URL` to
the doc's QA host (`http://public-fusionzafeedstore-qa1.westeurope.cloudapp.azure.com/v1/sync`)
for testing. A plaintext-`http://` base logs a one-line warning per call.

## Object types

| Fusion object | Where it lands |
| --- | --- |
| `<Listing>` `CreateOrUpdate` / `Snapshot` | `import_listings` (upsert on the Fusion `@id`, **never `fusionRef`** — the doc says `fusionRef` is not unique) |
| `<Delete><ListingRef>` | `lifecycle.withdraw_listings` — `status='Withdrawn'`, never a row removal |
| `<Office>` | `agencies` + `agency_vendor_ids` (upsert; `<Delete><OfficeRef>` → `status='Inactive'`) |
| `<Agent>` | `agents` + `agent_vendor_ids` (upsert; `<Delete><AgentRef>` → `status='Inactive'`) |
| `<AreaTree>` | flattened to `data/fusion/area_tree.json` — a `suburbId` → `{suburb, city, province}` crosswalk. The listing mapper hands the suburb **name** to the existing `resolve_suburb` (name / alternate-name match against our own `provinces` / `cities` / `suburbs` — **no parallel geography table**). An unresolved suburb still imports the listing with `suburb_id` NULL; after `EndSnapshot` a pass backfills `suburb_id` for listings whose AreaTree node arrived in a later batch. |
| `<Development>` | **deferred** — captured to `data/fusion/developments.json` + `raw_data.fusion_development_id`; `listings.development_id` stays NULL. See "Obligations / follow-ups". |

## Listing field mapping

| importer key | Fusion source |
| --- | --- |
| `vendor_listing_id` | `<Listing @id>` |
| `vendor_listing_type` | `Type/@listingZone` (`Residential` / `Commercial` / `Farm` / `Development`) — namespaces `resolve_property_type` |
| `listing_type` | `Type/@listingType` (`Sale` / `Rent`) |
| `property_type` | `Type/@propertyType` → explicit dict onto the seeded canonical types; unknown values fall through to `resolve_property_type` (name-ILIKE + the per-feed `property_type_vendor_mappings` table) |
| `title` | `Marketing/MarketingHeader`, else composed from type + suburb |
| `description` | `<Description>` text, `<br/>` → newline (the only tag the doc allows) |
| `price` / `price_on_application` | `SaleDetails/@sellingPrice` or `RentDetails/@rentalPrice`; POA when `@priceSuffix` ∈ {`POA`, `SBT`} |
| `bedrooms` / `bathrooms` / `garages` | `MainFeatures/@numBedrooms` / `@numBathrooms` / `@numGarages` |
| `parking_spaces` | `MainFeatures/@numCoveredParkings` + `@numOpenParkings` |
| `erf_size` / `floor_size` | `MainFeatures/@landArea` (+`@landAreaUnits` → m²) / `@floorArea` |
| `levies` / `rates_and_taxes` | `SaleDetails/@levy` / `@rates` |
| `street_address` | `Address` `@streetNumber` + `@streetName` + `@streetType` — **suppressed when `@addressHidden="true"`** (the doc's display rule) |
| `latitude` / `longitude` | `Address/@latitude` / `@longitude` (dropped when zero) |
| `suburb` | AreaTree crosswalk `[Address/@suburbId]` → name |
| `features` | `SecondaryFeatures` `has*` / `is*` flags → labels + `CustomFeatures/CustomFeature/@name` |
| `agency_vendor_id` / `agency_name` | `@officeId` / the Office event's name (else `@agencyName` — `@branchName`) |
| `agent_vendor_id` / `agent_name` | first `Agents/AgentRef/@id` / the Agent event's name |
| `listed_at` / `vendor_updated_at` | `@publishedDateTime` / the event `@timestamp` |
| `primary_image_url` | first `Photos/Photo/@url` (**hotlinked**) |
| `raw_data.fusion_*` | `fusionRef`, `agencyRef`, `suburbId`, `developmentId`, `importedFrom`, `featured`, `saleState`/`rentalState`, `mandateType`/`mandateExpiry`, `priceSuffix`, `deposit`, `virtualTourUrl`, `youTubeVideoId`, `addressHidden`, agent-ref ids, all `<Photo>` urls, `<Document>` urls, `SecondaryFeatures` count attrs, `<CommercialListingDetails>` / `<HolidayRentalDetails>` / `<CommercialFeatures>` attribute bags |

## Deliberately not mapped

1. **Photos are hotlinked, not downloaded.** The doc says photos "must download
   to local repository"; the operator chose to hotlink the Fusion CDN URLs (like
   propdata / propctrl / remax / propertyengine). `primary_image_url` and every
   `listing_media.url` are Fusion CDN URLs. Revisit if Fusion enforces this or
   the `next.config.ts` deny-all image policy needs them local — the shared
   `iol_importers.media` re-hosting layer (built for Entegral) is ready.
2. **`<Documents>` (brochures, floor plans)** — URLs kept in
   `raw_data.fusion_document_urls`, not downloaded, no `listing_media` rows.
3. **`<RentDetails>` / `<HolidayRentalDetails>` deposit, seasonal rates, lease
   terms** — the `listing_rental_details` table is not wired by the importer
   (same as every prior feed). Kept in `raw_data`.
4. **`<CommercialListingDetails>` / `<CommercialFeatures>`** — no canonical
   commercial columns; kept in `raw_data` as attribute bags.
5. **`<SellersAndLandlords>`** — owner names / ID numbers / contact details.
   Never mapped to any column; **dropped from the committed fixtures**.
6. **`<ShowDays>` (show-house times)** — no canonical table (same as the other
   feeds).
7. **`<Development>` → the `developments` table** — see follow-ups below.
8. **`SendEnquiry`** (Fusion's inbound-lead API) — a separate outbound
   integration, out of scope for the sync adapter.

## Obligations / follow-ups (outside this step)

1. **`NotifyChangesAvailable`** — Fusion calling *into* us on a client endpoint
   we would have to expose, to signal "the queue has data". **Not implemented**
   — this step is the polling side only. Building the webhook (verify the
   inbound SecurityToken, respond `<RequestCompleted/>` within a minute, do
   **not** call `GetChanges` from inside the handler) is separate later work.
2. **Canonical `developments` sync** — `developments` has no `feed_source_id`,
   no vendor-id map, and no soft-delete state, so a `<Development>` event can't
   be keyed or withdrawn idempotently without a `004` migration
   (`development_vendor_ids` + a status/withdrawn column). Until then, Fusion
   developments live in `data/fusion/developments.json` + `raw_data`, and
   `listings.development_id` is left NULL.
