# RT3 (Rawson) feed — mapping notes

Source: one bracket-KV file per province at
`https://webservices.rawsonproperties.co.za/iol-{Province}.txt` — a plain public
GET, **no auth of any kind**, ~17 MB / a few thousand listings per province.
Parsed by the shared `iol_importers.bracket_kv` module (not reimplemented here).
Full resend per province, no delta, no delete signal — absences are reconciled
**per province** with `lifecycle.withdraw.withdraw_missing`.

## Per-agency configuration

RT3 is a single brand ("Rawson Properties"). What is per-agency is **which
province files that agency publishes** — a JSON array of URL tokens on the
`feed_sources` row (the token is the exact `{Province}` URL segment, underscores
for spaces):

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
VALUES ('rt3-rawson', 'Rawson Properties (RT3)', 'RT3',
        'https://webservices.rawsonproperties.co.za',
        '{"provinces": ["Western_Cape", "Gauteng", "KwaZulu-Natal"]}');
```

`RT3_FEED_BASE_URL` (optional, in `.env.example` / `src/server/env.ts`) only
overrides the host. There is no credential.

## Run shape

1. **Every configured province file is fetched up front.** If any fetch fails
   the whole run aborts before anything is imported or reconciled — a province
   that came back broken must never cause its listings to be withdrawn.
2. All provinces' records are imported in **one** `import_listings` job.
3. Photos are hotlinked to `listing_media` (prune-missing).
4. **Per-province reconcile**: `withdraw_missing(code, province_seen_ids,
   raw_scope=("rt3_province", province))` — each province is reconciled against
   its own snapshot, scoped by `raw_data ->> 'rt3_province'`, so a province with
   an empty snapshot (skipped, never forced) or a province missing from this run
   never touches another province's listings.

## Listing field mapping

| record key | RT3 key | note |
| --- | --- | --- |
| `vendor_listing_id` | `Reference` | blank → counted validation reject |
| `title` | `Heading` | blank → `"{property_type} in {Suburb}"`, tallied (real data always has `Heading`) |
| `description` | `Description` | stripped only (multi-line paragraphs kept) |
| `property_type` | `Type` → crosswalk | see below |
| `listing_type` | `Status` | `For Sale` / `To Let` — the listing type, not a lifecycle state |
| `price` / `price_on_application` | `Price` | missing **or** `0` → POA |
| `bedrooms` / `bathrooms` | `Beds` / `Baths` | |
| `garages` / `parking_spaces` | `Garages` / `Carports` | |
| `floor_size` / `erf_size` | `Building_Size` / `Erf_Size` | m² |
| `street_address` | `Address` | present on some records only; the vendor sometimes omits the trailing `/` before `]]` (the shared parser tolerates it) |
| `suburb` | `Suburb` | name-matched, NULL if unresolved |
| `latitude` / `longitude` | `GPS` split on `,` | `""`, `"0,0"`, `"0.00000000,0.00000000"`, or both-zero → NULL/NULL |
| `agency_vendor_id` / `agency_name` | `Branch_ID` / `Branch_Name` | the branch is the agency-level entity; `"Rawson Properties"` goes to `raw_data.rt3_brand` |
| `agent_vendor_id` / `agent_name` | first agent: `lower(Email or Name)` / `Agent_Name` | see co-agents below |
| `features` | `Views`, `Security`, `Balcony`, `Patio`, `Garden` (comma-split tokens) + `Pool`, `Alarm`, `Laundry`, `Staff_Accomm`, `Ensuites` (boolean labels) | deduped; coerced to `text[]` by the importer |
| `primary_image_url` | first `Image_URL` | repeated key → all images hotlinked in order |
| `listed_at` | `Listed` | `YYYY-MM-DD` string passthrough; Postgres parses it |

### `Type` crosswalk (→ seeded `property_types`)

`House`, `Cluster`, `Commercial`, `Development`, `Office`, `Industrial`,
`Vacant Land`, `Farm` **self-map** via `resolve_property_type`'s case-insensitive
name match. `map._PROPERTY_TYPE` only lists the values that do not:

- Apartment family (`Bachelor`, `Flat`, `Loft Apartment`, `Penthouse`,
  `Maisonette`, `Cottage`, …) → **Apartment**; `Block of Flats` → **Apartment Block**
- `Duet`, `Townhouse - freehold`/`sectional`, `Duplex Townhouse - …` → **Townhouse**
- `Smallholding`, `Commercial - Farm (Agricultural Holding)` → **Farm**
- `Vacant Erf`, `Vacant Stand`, `Commercial - Vacant Land` → **Vacant Land**
- `Commercial - Offices` → **Office**
- `Commercial - Factory` / `Warehouse` / `Industrial` → **Industrial**
- `Commercial - Retail` / `Mixed Use` / `Other` / `Commercial Property` /
  `Conference/Wedding Venue` / `Block of Residential Flats` → **Commercial**

`Guest House`, `Commercial - Guest House`, `Unclassified` are **deliberately not
mapped** — they pass through raw so `resolve_property_type` raises `MappingError`
and the record is quarantined (`error_type='mapping'`), never guessed. (~1.2% of
the real 4,137-record Gauteng dataset.)

## Co-agents

RT3 carries numbered co-agent fields: `Agent_Name` / `Cell_No` / `Email` for the
first agent, then `Agent_Name_2` / `Cell_No_2` / `Email_2`, … for an arbitrary
number more. `map._agents` finds every `^(Agent_Name|Cell_No|Email)(?:_(\d+))?$`
key (unsuffixed = index 1), sorts by index, and builds the ordered roster —
handling **zero, one, many, and gappy** suffix sets.

Step 14 stores exactly one `agent_id` per listing, so:

- the **first** roster entry drives `agent_vendor_id` (`lower(email)`, or the
  name when there is no email) and `agent_name`;
- the **whole ordered roster** `[{name, email, cell}, …]` is kept in
  `raw_data.rt3_agents`, with `raw_data.rt3_co_agent_count` (= roster length − 1).

## raw_data

Every feed key not promoted to a column (and not an agent-roster key) is captured
under `rt3_<Key>` (a list when the key repeats). So `Details_URL`, `Office_No`,
`Area`, `Province`, `Study`, `Family_Rooms`, `Reception_Rooms`, `Levels`,
`onshowdate`, and any unknown future key are all kept. Plus explicit:
`rt3_province` (the config token — what the reconcile scopes on), `rt3_brand`
(`"Rawson Properties"`), `rt3_status`, `rt3_type` (raw), `rt3_gps_raw`,
`rt3_agents`, `rt3_co_agent_count`, `rt3_kitchen_fittings`.

## Deliberately not mapped / caveats

* **`Kitchens` is an underscore-token list** (`_extractor fan_, _gas hob_,
  _granite tops_`) — **unique to RT3**. `map._kitchen_fittings` parses it into an
  ordered list at `raw_data.rt3_kitchen_fittings`. It is **not** a feature and
  **not** a count. MyRoof and PropertyPost both use `Kitchens` as a plain
  count/flag — that logic is not shared with this adapter.
* **`Views` / `Security` / `Balcony` / `Patio` / `Garden` are free-text tag
  lists, not booleans** — every comma-split token is folded into `features`
  (user decision). `Study` / `Family_Rooms` / `Reception_Rooms` / `Levels` are
  numeric counts and stay in `raw_data`.
* **No agency-level field** — `Branch_ID` / `Branch_Name` are the office
  identity; every listing nationwide is "Rawson Properties".
* **No numeric agent id** — `Email` is the stable identifier.
* **No Rates / Levies / deposit / furnished field** exists in the feed.

## Parser

`iol_importers.bracket_kv` — the shared bracketed-KV parser (Step 23), also used
by the MyRoof and PropertyPost adapters. RT3's multi-line `Description` values
and its optional trailing `/` (`Address`, `onshowdate`) are both handled by it.
