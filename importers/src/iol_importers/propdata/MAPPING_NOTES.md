# Propdata field mapping — verified vs flagged

Derived by inspecting real API responses (`fixtures/`), not the docs (the docs
site is 403 on every listings path). The mapping in `map.py` covers only fields
confirmed against live payloads.

## Mapped (verified against real records)

| importer field | Propdata source |
| --- | --- |
| `vendor_listing_id` | `id` (numeric, stable) |
| `vendor_listing_type` | the category (`residential` / `commercial` / `holiday` / `projects`) |
| `listing_type` | `listing_type` ("For Sale" / "To Let"); **holiday → Rental, projects → Sale** |
| `property_type` | `property_type`; **projects → "Development"** |
| `title` | `marketing_heading` (projects: `name`) |
| `description` | `description` |
| `price` | `price` (projects: `min(property_types[].priced_from)`) |
| `price_on_application` | `poa` |
| `bedrooms` / `bathrooms` / `garages` | same names (projects: null — a range) |
| `parking_spaces` | `carports` |
| `floor_size` | `floor_size` |
| `erf_size` | `land_size` |
| `street_address` | `street_number` + `street_name` |
| `complex_name` | `complex_name` or `building_name` |
| `unit_number` | `unit_number` |
| `suburb` | `location` → `GET /locations/api/v1/locations/{id}/` → `suburb` |
| `agency_vendor_id` / `agency_name` | `branch` / branch lookup `name` |
| `agent_vendor_id` / `agent_name` | `agent` / agent lookup `full_name` |
| `listed_at` | `on_market_since` or `created` |
| `vendor_updated_at` | `modified` |
| `raw_data.propdata_*` | `web_ref`, `status`, `listing_images` ids, `location` id, `postal_code`, `property24_id`, project `plans` |

## Flagged — left unmapped rather than guessed

1. **`latitude` / `longitude`** — not present on the listing or the location record. Left NULL.
2. **`primary_image_url`** — `listing_images` is a list of image **ids**; `/file/api/v1/files/{id}/` returns 404. The URL-bearing endpoint has not been identified. Ids are kept in `raw_data.propdata_image_ids`.
3. **`features`** — no single list field. Residential exposes `extras` plus dozens of boolean amenity flags (`pool`, `borehole`, `security`, `solar_panel`, …); projects have `features` / `key_features`. Needs a decision on which to fold into `features TEXT[]`.
4. **`erf_size` vs `land_size` vs `floor_size`** — `land_size` mapped to `erf_size` provisionally; `*_measurement_type` fields are ignored (assumed m²).
5. **`status`** — the adapter requests `?status=Active`, so only live listings arrive. Non-active vendor statuses ("Sold", "Withdrawn") are not carried into the `listing_status` enum; disappearance is handled by `last_seen_at` + the expiry sweep.
6. **Commercial `price` semantics** — for a "To Let" commercial unit, `price` looks like a **rate** (e.g. `150.00` with a `128 m²` unit ≈ R19 200/month per the description), not a total. `gross_monthly_rental` may be the intended total. Mapped `price` as-is; revisit.
7. **Rental specifics** — `deposit`, `lease_period`, `available_from`, `furnished`, `price_term` ("Per Month") are not carried; `listing_rental_details` is not yet wired in the importer.
8. **holiday** — 0 listings exist in this vendor account across all 138 clients. The holiday mapping is inferred from the residential shape and is exercised only by a hand-built fixture; unverified against live data.
9. **projects** — one listing per project; per-plan detail (Studio / 1-bed / 2-bed pricing) is preserved only in `raw_data.propdata_plans`. Domain 5 (`developments` / `development_listings`) is where this should eventually land.

## Auth flow (verified)

- **Login**: `GET {PROP_DATA_API_LOGIN_URL}` + `Authorization: Basic base64(user:pass)` → `{ clients: [ { site: { domain }, token }, … ] }`. One token per client; the account has 138.
- **Renew**: `GET https://api-gw.propdata.net/users/api/v1/renew-token/` + `Authorization: Bearer <token>` → 200; **the new token is in the `token` response header** (the body is the user object).
- All listing/lookup endpoints: `Authorization: Bearer <token>`.
- Pagination: DRF `{ count, next, previous, results }`; `next` is an absolute `?limit=&offset=` URL, followed to `null`.
