# AllSA Property feed — mapping notes

Source: `https://www.allsaproperty.co.za/feeds/iol.ashx?agencyid={agencyid}`
(public, unauthenticated). One HTTP GET returns an agency's **whole book** as
`<Listings><Property>…</Property></Listings>` — a flat list, no office grouping,
no delta endpoint, no deletion signal. Full-resend semantics, same as the
PropertyEngine feed: reconcile absences with `lifecycle.withdraw.withdraw_missing`.

## Per-agency configuration

Each AllSA agency is its own `feed_sources` row. The `agencyid` query parameter
is **not** in the source tree — it is `auth_config->>'agency_id'`:

```sql
INSERT INTO feed_sources (code, name, vendor_name, format, base_url, auth_config)
VALUES ('allsa-10173', 'National Real Estate', 'AllSA Property', 'XML',
        'https://www.allsaproperty.co.za/feeds/iol.ashx',
        '{"agency_id": "10173"}');
```

Run: `allsa-import --feed-source allsa-10173`. `vendor_listing_id` is the bare
`Reference`; it is only proven unique within one agency's feed, but the importer
keys on `(feed_source_id, vendor_listing_id)` so a cross-agency collision is
structurally impossible.

## Office identity — `BranchId`, not `Agency_Location`

One `agencyid` feed spans multiple offices. The real `agencyid=10173` feed
contains **four** `BranchId` values (10173, 10244, 10250, 10245), each with a
stable `Agency` name and `Agency_Website`. `Agency_Location` is the *listing's*
servicing town (52 distinct values inside BranchId 10173 alone) and is kept only
in `listings.raw_data.allsa_agency_location`.

`BranchId` → `agencies` + `agency_vendor_ids`; `lower(Agent_Email)` → `agents` +
`agent_vendor_ids` (`reference.py`). Both are find-via-vendor-id-then-update
upserts and run before `import_listings`, so the importer's own resolvers link to
the enriched row instead of creating a name-only stub.

## Listing field mapping

| record key | Property source | note |
| --- | --- | --- |
| `vendor_listing_id` | `Reference` | numeric, unique within the feed |
| `title` | **`Heading`** | the headline |
| `description` | `Description` | plain text (no HTML seen in the real feed) |
| `property_type` | `Type` via `_PROPERTY_TYPE` | free text; unmapped values pass through to `resolve_property_type` |
| `listing_type` | `Status` | `For Sale` / `To Rent` / `To Let` all accepted; the importer normalises to the `Sale`/`Rental` enum |
| `price` / `price_on_application` | `Price` | `0.00` → POA |
| `suburb` | `Suburb` | name → `resolve_suburb`; `CityTown`/`Province` kept in `raw_data` |
| `bedrooms` `bathrooms` `garages` `parking_spaces` `erf_size` `floor_size` `levies` `rates_and_taxes` `features` | `Features/*` | see below |
| `agency_vendor_id` / `agency_name` | `BranchId` / `Agency` | |
| `agent_vendor_id` / `agent_name` | `lower(Agent_Email)` / `Agent_Name` | |
| `primary_image_url` | first `Images/Image` | hotlinked, not re-hosted |

`listed_at` / `vendor_updated_at` stay `NULL` — the feed carries no timestamps.

## `Features` parsing (`features.py`)

`<Features>` is a free-form bag: the child set varies per listing and the real
feed shows **28 distinct tags** — an illustrative list, not a contract. The parser
**iterates the actual children** against a registry:

* counts → `bedrooms` / `bathrooms` / `garages` columns; `Carports + Parking` sum
  → `parking_spaces`; `Lounges` / `Dining_Areas` / `En_Suite` → `listings.features`
  labels;
* `Erf_Size` / `Floor_Size` → `erf_size` / `floor_size` (m²);
* `Land_Size` unit is **inconsistent** in the real feed — most values are
  hectares (`1`, `4.28`, `8.5`) but some are already square metres (`10712` for a
  listing whose own description says "1.0712HA"). Heuristic: a value `>= 1000` is
  taken as m², below that as hectares (`× 10 000`). The result backfills
  `erf_size` **only when `Erf_Size` is absent** and it fits `numeric(10,2)`;
  otherwise the raw value stays in `raw_data.allsa_features_extra`;
* `Rates` / `Levies` → `rates_and_taxes` / `levies`;
* `Yes`-valued flags (`Swimming_Pool`, `Study`, `Borehole`, …) → labels;
* `Available` → `raw_data.allsa_available_from`;
* **anything else** → `raw_data.allsa_features_extra[tag]` (+ a label if the value
  is `Yes`), and the tag is tallied in the run output so a new vendor feature is
  visible rather than silently dropped.

**Repeated children.** `<Features>` tags repeat within one `<Property>` in the
real feed — listing `2509202` carries each of its 10 tags 1852 times. The parser
keeps the first occurrence per tag and counts the drops
(`AllsaRunResult.duplicate_feature_elements`).

## Deliberately not mapped

* **`Title`** — this is *tenure* (`Freehold` / `Sectional Title`), not a headline.
  There is no canonical tenure column; kept in `raw_data.allsa_tenure`.
* **`Agent_Title`** (job title, e.g. "Candidate Property Practitioner") — no
  canonical `agents` column; kept in `raw_data.allsa_agent_title`.
* **`Rental_Period`** ("Per Month") — the importer has no rental-frequency field;
  kept in `raw_data.allsa_rental_period`.
* **Photos are hotlinked**, not downloaded. AllSA states no re-hosting
  requirement (unlike Entegral). `raw_data.allsa_image_urls` holds the full list.
* **`Available`** date on a rental → `raw_data.allsa_available_from` only; no
  availability column.

## Discrepancies from the brief

* The brief said `Status` maps to "For Sale" / "To Let"; the real feed sends
  **`For Sale` and `To Rent`**. Both (and "To Let") are handled.
* The brief's Features list is illustrative — the parser does not assume it.

## Obligations / follow-ups

* Seeding a `feed_sources` row per agency is a manual step (feed sources are
  configuration, never created by an import run).

## XML parser

Stdlib `xml.etree.ElementTree` — no `lxml` / `defusedxml` (no new tooling). It
resolves no external entities and does no network I/O; the residual
internal-entity-expansion risk is accepted for a trusted vendor over TLS, the
same call `iol_importers.fusion` makes. `defusedxml` is a possible later
hardening.
