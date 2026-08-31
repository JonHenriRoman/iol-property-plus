# MyRoof feed — mapping notes

Source: `https://rat.myroof.co.za/{token}` — one HTTP GET per franchise returns
that franchise's whole book as the bracketed key-value text format shared by RT3,
MyRoof and PropertyPost. Parsed by the shared `iol_importers.bracket_kv` module
(not reimplemented here). Full resend, no delta, no delete signal — absences are
reconciled with `lifecycle.withdraw.withdraw_missing`.

## Per-franchise configuration

The opaque `{token}` path segment is the entire credential (no auth header). It is
**per-franchise config on the `feed_sources` row**, never in the source tree, an
env var, a log line, or the run result:

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
VALUES ('myroof-acme', 'Acme Realty (MyRoof)', 'MyRoof',
        'https://rat.myroof.co.za', '{"token": "<opaque feed token>"}');
```

`MYROOF_FEED_BASE_URL` (optional, in `.env.example` / `src/server/env.ts`) only
overrides the host — not the token.

## Listing field mapping

| record key | MyRoof key | note |
| --- | --- | --- |
| `vendor_listing_id` | `Reference` | |
| `title` | `Heading` | |
| `description` | `Description` | `<p>` / `</p>` / `<br>` → newline, entities unescaped, blank runs collapsed |
| `property_type` | `Type` → crosswalk | see below |
| `listing_type` | `Status` | only `For Sale` confirmed (see caveats) |
| `price` / `price_on_application` | `Price` | missing **or** `0` → POA |
| `bedrooms` / `bathrooms` / `garages` | `Beds` / `Baths` / `Garages` | |
| `floor_size` / `erf_size` | `Building_Size` / `Erf_Size` | m² |
| `street_address` | `Address` | |
| `suburb` | `Suburb` | name-matched, NULL if unresolved |
| `latitude` / `longitude` | `GPS` split on `,` | bare-comma sentinel → NULL/NULL |
| `agency_vendor_id` / `agency_name` | `Branch_ID` / `Branch_Name` | always `1` / `MyRoof.co.za` (single brand) |
| `agent_vendor_id` / `agent_name` | `lower(Email)` / `Agent_Name` | Agent_Name is a program label, not a person |
| `features` | `Garden`, `Staff_Accomm`, `Pool` (`Yes`/`1`) + always `Repossession` | |
| `primary_image_url` | first `Image_URL` | hotlinked to `listing_media`, not re-hosted |
| `listed_at` | `Listed` | `2010-10-28 21:50:48.000` — passed through; Postgres parses it |

### `Type` crosswalk (→ seeded `property_types`)

`House` / `Freehold Residence` → **House**; `Apartment` /
`Open Plan Bachelor/Studio Apartment` → **Apartment**; `Complex` → **Townhouse**;
`Plot` → **Vacant Land**; `Agricultural` → **Farm**; `Commercial` → **Commercial**.
`Guest House` is deliberately **not** mapped — it passes through raw so
`resolve_property_type` raises `MappingError` and the record is quarantined
(`error_type='mapping'`), never silently defaulted.

## raw_data

Every feed key that is not promoted to a column is captured under `myroof_<Key>`
(a list when the key repeats). So `Video_URL`, `Kitchens`, `Living_Rooms`,
`Dining_Rooms`, `Study`, `Family_Rooms`, `Ensuites`, `Carports`, `Area`,
`Details_URL`, `Office_No`, `Cell_No`, `Province`, and any unknown future key are
all kept. Plus explicit `myroof_agent_program` (= `Agent_Name`), `myroof_status`,
`myroof_type` (raw), `myroof_gps_raw`.

## Deliberately not mapped / caveats

* **`Description` `<p>` tags are not real HTML** — MyRoof uses them as paragraph
  breaks and nothing else. They are converted to newlines; a raw `<p>` never
  reaches `listings.description`.
* **`Agent_Name` is a lender/repossession-program label** ("Standard Bank
  Repossessed", "FNB Quick Sell", "SA Home Loans Sell Assist" — ~10 values). It is
  used as the agent's name because that is what the feed calls the seller, and is
  also kept in `raw_data.myroof_agent_program`. `Email` is the stable
  per-"agent" id. The whole feed is bank-repossessed stock — hence the synthetic
  `Repossession` feature on every record.
* **Only `Status = "For Sale"` is confirmed** (3,857 real records, all Sale). The
  importer's `normalize_listing_type` already handles `to let` / `to rent` if a
  rental ever appears, but the exact rental wording is unverified.
* **One agent per listing** — no RT3-style numbered co-agents seen. Treated as
  current reality; not asserted permanently.
* **`Kitchens` is a plain integer count** here, unlike RT3's underscore-wrapped
  list (`_gas hob_, _granite tops_`). No RT3 parsing logic is used — it goes
  straight to `raw_data.myroof_Kitchens` as-is.
* **`Video_URL` → `raw_data.myroof_Video_URL` only.** MyRoof carries YouTube /
  360-tour links as a repeated media field; promoting them to `listing_media`
  rows (`media_type='Video'`) is a follow-up, not this step.
* **No Rates / Levies / deposit / furnished field** exists in the feed.

## Parser

`iol_importers.bracket_kv` — the shared bracketed-KV parser (Step 23). The literal
`/` in `Type: Open Plan Bachelor/Studio Apartment` and in URLs is preserved by it;
only the `/]]` terminator is stripped.
