# PropertyPost feed — mapping notes

Source: one static per-agency URL, e.g.
`http://lms.propertypost.co.za/BstProperties.txt` — a plain HTTP GET (redirecting
to HTTPS), **no auth header, no query token, no credential of any kind**, returns
that agency's whole book as the bracketed key-value text format shared by RT3,
MyRoof and PropertyPost. Parsed by the shared `iol_importers.bracket_kv` module
(not reimplemented here). Full resend, no delta, no delete signal — absences are
reconciled with `lifecycle.withdraw.withdraw_missing`.

## Live findings (real 197-record fetch, 2026-08-31)

| Question | Answer from the live feed |
| --- | --- |
| Separate to-let URL, or one file? | **One file.** `Status` is `For Sale` (159) or `To Let` (38) in the same response. The two review samples were just split for convenience. |
| Single-agency or multi-agency per URL? | **Single agency** — `Branch_ID` `39350` / `Branch_Name` `BST PROPERTIES (PTY) LTD` on all 197 records. But agency identity is resolved **per record**, so a multi-branch file would work with no code change; `PropertypostRunResult.branches` reports the distinct set on every run. |

Other real findings:

- **`Beds`/`Baths` duplicate `Bedrooms`/`Bathrooms`** on every record — the same
  fact under two names. Agree on 195/197; the two exceptions are "one side blank"
  (`5053704`, `5074205`), never two different numbers. `_coalesce_pair` takes
  `Bedrooms`/`Bathrooms` and falls back to `Beds`/`Baths` when a side is blank.
- **`GPS` is simply absent** on 26/197 records — no `"0,0"` and no bare comma,
  the field just isn't there.
- **`Features_Description` is empty on 120/197** and free-text prose on the rest,
  e.g. `Land Area - 12217 - Mother erf   Aircon - YES - 4`. Sometimes the only
  place a levy figure appears. Kept verbatim; **never parsed**.
- **`Heading` empty on 2/197** — otherwise complete listings, so a title is
  synthesized rather than the record rejected.
- **17 duplicate `Reference` occurrences across 12 references** (180 distinct of
  197). Byte-identical; the `UNIQUE (feed_source_id, vendor_listing_id)` upsert
  makes each a no-op.
- **~444 trailing bare `[[Listing_Start]]` tags** pad the file; `bracket_kv` only
  emits on `[[Listing_End]]`, so they are dropped by construction.
- **All 14 amenity keys are pure `YES` booleans** — `Fence`, `Alarm`, `Garden`,
  `Pool`, `Security`, `Patio`, `Balcony`, `Views`, `Staff_Accomm`, `Laundry`,
  `Study`, `Family_Rooms`, `Reception_Rooms`, `Kitchens`. `Kitchens: YES` is a
  feature flag here — not MyRoof's count, not RT3's embedded list.
- `Ensuites`, `Levels`, `Living_Rooms`, `Dining_Rooms` are numeric counts with no
  canonical column → `raw_data`.
- **`Admin_ID` is a constant company contact** (`brendan@bstproperties.co.za` on
  all 197) while `Agent_Name`/`Email` vary across 14 real agents — kept as
  `raw_data.propertypost_admin_email`, never used as the agent identity.
- `Price` is a decimal string (`1550000.00`), min `3500`, max `40000000`, no
  zeros observed — POA handling is defensive only. `Erf_Size`/`Building_Size` do
  carry literal `0`, which becomes NULL, not a 0 m² fact.

## Per-agency configuration

There is no credential, so the per-agency value is the full URL itself (its
filename identifies the agency) — it lives on the `feed_sources` row's `base_url`:

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url)
VALUES ('propertypost-bst', 'BST Properties (PropertyPost)', 'PropertyPost',
        'http://lms.propertypost.co.za/BstProperties.txt');
```

`PROPERTYPOST_FEED_BASE_URL` (optional, in `.env.example` / `src/server/env.ts`)
only supplies a default host for a row whose `base_url` is a bare host with no
`/<file>` path.

## Listing field mapping

| record key | PropertyPost key | note |
| --- | --- | --- |
| `vendor_listing_id` | `Reference` | blank → counted validation reject (the only hard reject) |
| `title` | `Heading` → `Description` first line → `"{property_type} in {suburb}"` | synthesized fallbacks are tallied in the run result |
| `description` | `Description` | stripped only — no `<p>` tags in this feed |
| `property_type` | `Type` → crosswalk | see below |
| `listing_type` | `Status` | `For Sale` / `To Let`; `normalize_listing_type` handles both |
| `price` / `price_on_application` | `Price` | missing **or** `0` → POA (defensive) |
| `bedrooms` / `bathrooms` | `Bedrooms` ‖ `Beds` / `Bathrooms` ‖ `Baths` | coalesced; disagreement → `raw_data.propertypost_<field>_conflict` + tally |
| `garages` / `parking_spaces` | `Garages` / `Carports` | |
| `floor_size` / `erf_size` | `Building_Size` / `Erf_Size` | m²; a literal `0` → NULL |
| `street_address` | `Address` | present on 127/197 |
| `suburb` | `Suburb` | name-matched, NULL if unresolved |
| `latitude` / `longitude` | `GPS` split on `,` | key absent → NULL/NULL, no sentinel |
| `agency_vendor_id` / `agency_name` | `Branch_ID` / `Branch_Name` | **per record**, never from config |
| `agent_vendor_id` / `agent_name` | `lower(Email)` / `Agent_Name` | 14 real agents; `Admin_ID` is deliberately not the agent |
| `features` | the 14 `YES` flags → labels | `Staff_Accomm` → Staff Accommodation, `Family_Rooms` → Family Room, `Reception_Rooms` → Reception Room, `Kitchens` → Kitchen |
| `primary_image_url` | first `Image_URL` | hotlinked to `listing_media`, not re-hosted |
| `listed_at` / `vendor_updated_at` | `Listed` / `Verified` | `2022-06-17 11:17:50` (no fractional seconds) — passed through; Postgres parses them. `Verified` = "vendor last confirmed", not "last edited" |

### `Type` crosswalk (→ seeded `property_types`)

`House` → **House**; `Commercial` → **Commercial**; `Townhouse` → **Townhouse**;
`Apartment Or Flat` / `Flat` → **Apartment**; `Stand` → **Vacant Land**;
`Smallholding` → **Farm**. Every one of the 7 real values maps. An unmapped value
still passes through raw so `resolve_property_type` raises `MappingError` and the
record is quarantined (`error_type='mapping'`), never silently defaulted.

## raw_data

Every feed key that is not promoted to a column is captured under
`propertypost_<Key>` (a list when the key repeats), so `Details_URL`, `Office_No`,
`Cell_No`, `Features_Description`, `Living_Rooms`, `Dining_Rooms`, `Ensuites`,
`Levels`, and any unknown future key are all kept. Plus explicit aliases:
`propertypost_status`, `propertypost_type` (raw), `propertypost_admin_email`
(= `Admin_ID`), `propertypost_city` (= `Area`), `propertypost_province`. A
duplicate-field disagreement adds `propertypost_bedrooms_conflict` /
`propertypost_bathrooms_conflict`.

## Deliberately not mapped / caveats

* **`Beds`/`Baths` vs `Bedrooms`/`Bathrooms` is a real feed quirk, not a parser
  bug.** Handled explicitly by `_coalesce_pair` — one value, one bedroom fact,
  and a real disagreement is surfaced rather than lost.
* **`Features_Description` is not parsed.** The `Label - Value - Detail` triples
  (and the levy figure occasionally buried in them) are free-text prose with no
  consistent structure — a regex extraction would be fragile. Stored verbatim.
* **`Admin_ID` is not the agent.** It is a single company-wide contact; the agent
  is `Agent_Name` / `Email`.
* **No Rates / Levies / deposit / furnished field** exists in the feed as its own
  tag.
* **Suburb resolution** is name-match only (as every adapter) — an unresolved
  `Suburb` leaves `suburb_id` NULL and the listing still imports.

## Parser

`iol_importers.bracket_kv` — the shared bracketed-KV parser (Step 23), also used
by the MyRoof adapter. Multi-line `Description` values (195/197 records span
several physical lines) are only readable because the parser accumulates them;
literal `/` inside values and URLs is preserved.
