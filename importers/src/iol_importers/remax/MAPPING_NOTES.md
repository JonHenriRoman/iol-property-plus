# RE/MAX field mapping — verified vs. deliberately unmapped

Source: *RE/MAX Feeds Documentation V1.6* (`~/Documents/setup-guides/Feed_Documentation_V1.6.pdf`),
**corrected against the live API** during planning. Several things differ from the doc.

## The contract (as verified live)

- **Auth — both layers.** Every request is `POST` + JSON body, AWS SigV4-signed
  (`service=execute-api`, `region=eu-west-1`, signed headers
  `host;x-amz-content-sha256;x-amz-date`) **and** carries an `x-api-key: <api_key>`
  header. SigV4 alone → `403 Missing Authentication Token`; `x-api-key` alone →
  `403 Forbidden`; both → `200`. The body also repeats the key as `token` (doc).
- **Double-encoded envelope.** Responses are `{"Success": true, "data": "<JSON
  string>"}` — `data` must be `json.loads()`d a second time.
- **`504` / `500`.** API Gateway's 30 s ceiling trips on Lambda cold starts
  (`504`); the client retries with backoff. `/lists {listings:true}` returns
  `500` **persistently** — genuinely broken server-side.

## Endpoint reality vs. the doc

| Endpoint | Doc | Reality |
| --- | --- | --- |
| `/lists {listings:true}` (+`start_date`) | full / incremental listing dump | **HTTP 500** — not used |
| `/lists {offices:true}` / `{agents:true}` | id lists | ✅ (`agents` list **has duplicates** — dedupe on `agent_id`) |
| `/lists-pagenate {listings:true, start_date?, page}` | paginated listings | ✅ used for **incremental**; `start_date` filters correctly; thin shape (`property_id, price, heading, date_last_updated, published_datetime`) |
| `/agents-page {agent_id, page}` | full agent+listings | ✅ used for **full**; `properties.property[]` is the full shape; `agent_details` + `branches.branch_details[]` inline |
| `/listing {listing_id}` | full single listing | ✅ used to hydrate incremental ids; full shape + inline `agents` + `office` |
| `/lists_deleted {listings:true}` | "not paginated, 7 days" | **IS paginated**; ~17 000 rows; `{property_id, date_deleted}` → soft-delete |
| `/office-pagenate`, `/office`, `/agent` | — | not wired (`agents-page` covers full listings + branch data) |

## Mapped (controlled vocabularies are explicit, never inferred)

| importer field | RE/MAX source |
| --- | --- |
| `vendor_listing_id` | `property_id` |
| `listing_type` | `listing_type` — `{"For Sale","To Rent"}` only; else `Unknown` |
| `property_type` | **base segment** before the first `:` → `{House, Apartment/Flat→Apartment, Townhouse, Vacant Land / Plot→Vacant Land, Farm, Commercial Property→Commercial, Industrial Property→Industrial}`. The `: subtype` (`Office`, `Retail`, `Hotel`, `residential`, junk) → `raw_data.remax_property_type_subtype` |
| `title` / `description` | `heading._cdata` (fallback `marketing_header`) / `description._cdata` with HTML stripped |
| `price` / `price_on_application` | `price.amount` / `price.poa` |
| `bedrooms`/`bathrooms`/`garages` | `features.{bedrooms,bathrooms,garages}` (`0` treated as "unspecified" → NULL) |
| `parking_spaces` | `features.covered_parkings` + `features.open_parkings` |
| `erf_size` / `floor_size` | `features.{erf_size,floor_size}` (units always `sqm`) |
| `levies` / `rates_and_taxes` | `features.levy` / `features.rates` |
| `suburb` | `location.suburb._cdata` |
| `street_address` | `address.street_number` + `address.street_name` (usually empty) |
| `features` | every `features.*` boolean-string that is `"true"` → a title-cased label, plus `custom_features` split on `,` |
| `primary_image_url` | first active `photos.photo[]` by `order` |
| `agency_vendor_id` / `agency_name` | `office.office_id` / `branch_id` · `office.name` |
| `agent_vendor_id` / `agent_name` | `agent.agent_id` · `first_name + (surname\|last_name)` |
| `listed_at` / `vendor_updated_at` | `published_datetime` / `date_last_updated` |
| `raw_data.remax_*` | `reference`, `listing_state`, `mandate_type`, `price_periodicity`, `property_type_raw`/`_subtype`, `land/floor_area_units`, `listing_link`, `media` URLs, `photo_count`, city/province, room-count ints (`num_en_suite`, `lounges`, `dining_rooms`, `flatlets`, `storys`) |

`price.periodicity` (`"Per Month"` for rentals) → `raw_data.remax_price_periodicity` — it changes what `price` means, and there is no column for the pricing basis.

## Deliberately not mapped

1. **`/lists {listings:true}`** — the doc's headline endpoint. HTTP 500. `/lists-pagenate` used instead for incremental (a deviation from the objective's wording, forced by the server).
2. **`geo_location` / `address`** — `geo_location` is always `""`/`"0"`; `address` is usually empty. `latitude`/`longitude` left NULL; `street_address` NULL unless the address block is populated.
3. **`listing_state`** (`New` / `Price Reduced` / `Sold` / `Leased`) — a display status, not the `listing_status` enum. Kept in `raw_data`. `Sold`/`Leased` disappearance is handled by `/lists_deleted` + the expiry sweep.
4. **Agent soft-delete** (`/lists_deleted {agents:true}`) — agents are shared canonical rows, not feed-owned. Withdrawing one because RE/MAX dropped it could hide an agent still active via another feed. Deferred.
5. **`rental_details`** (`pets_allowed`, `furnished`, deposit, lease terms) — the `rental_details` table is not wired in the importer (as with propdata/propctrl). Rental booleans still land in `features[]`.
6. **`media` virtual-tour / video URLs** — no `listing_media` table wired; URLs kept in `raw_data.remax_media_urls`.
7. **`custom_features` free text** — appended to `features[]` verbatim; not normalised to canonical amenity names.
8. **`num_en_suite` / `lounges` / `dining_rooms` / `flatlets` / `storys`** — no columns; kept in `raw_data`.

## Change-skipping and deletions

- Before upserting, `listings.last_updated_by_vendor_at` is compared with the
  record's `date_last_updated`; `feed_ts <= stored` → the record is **skipped**,
  not re-upserted (counted `skipped_unchanged`).
- `/lists_deleted` ids → `lifecycle.withdraw_listings()`:
  `UPDATE listings SET status='Withdrawn', expired_at=now() WHERE … AND status <> 'Withdrawn'`.
  Never deletes a row; idempotent; only touches listings that exist.
