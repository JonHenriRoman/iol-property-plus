# PropertyEngine mapping notes

Source: **Gumtree Pro "Real Estate Standard Template Feed" v1.0.1** (2023-12-12),
`~/Documents/setup-guides/2RealEstate_StandardTemplate_GumtreePro (1) (2).pdf` —
Gumtree's own prescribed outbound schema, which PropertyEngine implements to
syndicate listings to IOL Property.

## Feed shape

Root: `{ "Listings": { "Property": [ ... ] } }` (JSON) or `<listings><Property>…`
(XML). The doc specifies JSON; the only PropertyEngine feed observed in practice
(sibling repo `iol-property/packs/propertyengine`, 1084 live listings) is **XML**
with the same field semantics. `decode.py` sniffs the first non-whitespace byte
and normalises both into one nested-dict shape.

Real casing drift the decoder absorbs (case-insensitive, alias-tolerant `get()`):
`status` (doc: `Status`), `agent` (doc: `Agent`), `email` on `Office` (doc:
`Email`), `AgentId` (doc: `AgentID`), `CityTown` (doc: `City`).

## Field mapping

| Feed field | `import_listings` key | Notes |
| --- | --- | --- |
| `UniqueID` | `vendor_listing_id` | The upsert key. The doc guarantees only `UniqueID` / `AgentID` / `OfficeID` unique + static; `Reference` explicitly is not. |
| `Heading` | `title` | Whitespace-collapsed. There is no `heading` column — it is `listings.title` (NOT NULL). |
| `Description` | `description` | Whitespace-collapsed. |
| `Status` | `listing_type` | `For Sale`→Sale, `To Let`→Rental, `Holiday`→Rental (see below). |
| `Type` | `property_type` | Full Appendix B table, mapped explicitly (see below). |
| `Price` | `price`, `price_on_application` | `0` → "Contact for Price" (`price=None`, PoA=True), per the doc. A *missing* `Price` tag is not `0`. |
| `PropertySize` | `floor_size` → `floor_size_sqm` | No unit field anywhere; sqm assumed. Absent → `None`, never `0`. |
| `ErfSize` | `erf_size` → `erf_size_sqm` | Undocumented but present on real records. |
| `Bedrooms` | `bedrooms` | **Absence means studio, not zero** (doc: "Remove for studio"). Left `None`. |
| `Bathrooms` | `bathrooms` | |
| `Garages` | `garages` | Undocumented but present on ~half of real records. |
| `Rates` / `Levy` | `rates_and_taxes` / `levies` | Undocumented but present. |
| `MapYCoordinate` / `MapXCoordinate` | `latitude` / `longitude` | Y = latitude (negative in SA), X = longitude. Falls back to the Appendix A centroid when the record has no coords of its own. |
| `Suburb` / `City`\|`CityTown` / `Province` | `suburb` (+ raw city/province) | Used when `Location` is absent. `resolve_suburb` matches suburb name only. |
| `Location` | `suburb` candidate + `raw_data` | Appendix A gazetteer id. See "Location resolution" below. |
| `CreatedOn` | `listed_at` | |
| `UpdatedOn` | `vendor_updated_at` → `last_updated_by_vendor_at` | |
| `Images.Image[].ImageURL` | `primary_image_url` (first) + `listing_media` | Ordered; hotlinked, not re-hosted. |
| `Agents[0].Agent.AgentID` | `agent_vendor_id` | First agent only — the same single-FK limit every adapter documents. |
| `Agents[0].Agent.AgentName` | `agent_name` | |
| `Office.ID` | `agency_vendor_id` | There is **no agency level above `Office`** in this schema; `Office` maps onto `agencies`, as RE/MAX / Entegral offices do. |
| `Office.Name` | `agency_name` | |
| `Parking` | `features` | Single-element list when present (free text, "Garage" the only value seen live). |

Everything not promoted (`Reference`, `ListingType`, `PricePrefix`, `AvailableFrom`,
`AgentPhone`/`AgentMobile`/`AgentEmail`/`AgentPhoto`, the full `Office` contact
block, an unresolved `Location` id) is kept verbatim in `listings.raw_data` under
`propertyengine_*` keys.

## `listing_type`

`listings.listing_type` is the enum `('Sale', 'Rental', 'Unknown')` — **there is no
`Holiday` value**, and the shared `normalize_listing_type` has no `holiday` token.
Mapped in-adapter: `Holiday` → `To Let` → `Rental`. A short-term holiday let is
still a rental; the original word is kept as `propertyengine_status` in `raw_data`,
so a distinct holiday product later loses nothing.

## `property_type` — the full Appendix B vocabulary

All 41 documented `Type` values are mapped explicitly in `map.py::_PROPERTY_TYPE`
to a `property_types.name`. Nothing in-vocabulary ever errors. A `Type` **outside**
Appendix B is a validation failure (`error_type='validation'`), never a silent
default. Judgement calls:

- `Flat` → our distinct **Flat Apartment** row, not collapsed into Apartment.
- Hospitality (`Bed & Breakfast`, `Guest House`, `Guesthouse`, `Hotel`,
  `Hotel Room`) → **Commercial** — we have no hospitality taxonomy.
- Legal / structural descriptors (`Freehold`, `Freestanding`, `Bungalow`, `Villa`)
  → **House**.
- `Gated Estate` → **Residential Estate**.
- `Mini Factory` and `Minifactory` are two separate rows in the doc's own tables
  (a real spelling variant, not our typo) — both → **Industrial**, identically.
- `Storage Unit`, `Factory`, `Industrial Yard`, `Warehouse` → **Industrial**.

An in-vocabulary `Type` whose target `property_types` row does not exist raises
`MappingError` (`error_type='mapping'`) from the shared resolver — that is a
seed-data gap, not a feed problem.

## Location resolution (Appendix A)

Appendix A is a `LocationID → SA -> Province -> [Area ->] Locality` gazetteer with
a lat/long centroid, transcribed once into `locations.csv` (verified: unique ids,
known SA provinces, coordinates inside the SA bounding box). It is **not**
suburb-level in general — most rows are a city/town; some metro rows are a real
suburb. It has no link to our Property24-derived `suburbs` id space.

- `Location` present, in the gazetteer → its locality name is the suburb
  candidate (resolves for metro suburb rows; lands `suburb_id` NULL for city rows
  — the listing still imports); its province / area / centroid go into `raw_data`.
- `Location` present, **not** in the gazetteer → a per-run warning + a
  `propertyengine_location_unresolved` raw key. Not a record rejection: a stale
  gazetteer is our problem, not the vendor's.
- `Location` absent → the documented fallback: free-text `Suburb` / `City`
  (`CityTown`) / `Province`.

In the observed live feed, `Location` was never populated — every one of 1084
records used the free-text fallback.

## Validation

`validate.py` rejects a record (`error_type='validation'`) on a **value** breach:
missing `UniqueID` or `Heading`; `Type` outside Appendix B; `Status` not
`For Sale`/`To Let`/`Holiday`; `CreatedOn`/`UpdatedOn` not `yyyy-mm-dd HH:mm:ss`;
a space in `AgentPhone`; a malformed `AgentEmail` / `Office.Email`; no geography
at all (neither `Location` nor `Suburb`+`City`+`Province`).

The doc's Pascal-case / no-underscore **tag-name** conventions are counted per run
and logged, never rejected — the real feed sends lowercase `status` / `agent` /
`email`, and rejecting on that would quarantine 100% of the observed feed.

## Deliberately not mapped

- `PricePrefix` ("Asking Price"), `ListingType` (Gumtree's own precomputed Mapped
  Category), `AvailableFrom` (rental-only date), `AgentMobile` / `AgentPhoto`,
  `Office.TelephoneNumber` / `FaxNumber` / `PhysicalAddress` — no canonical column;
  kept in `raw_data`.
- Multiple agents — only `Agents[0]` is used (`listings` has one `agent_id`).
- Photos are **hotlinked**, not re-hosted. Nothing in this vendor's terms requires
  the media store (only Entegral's do).
- No lifecycle field exists anywhere — no Sold / Withdrawn / Let signal. `Status`
  is the market type, not a state. Disappearance is handled by per-feed
  reconciliation + the `iol-expire-listings` sweep.

## Still needed from PropertyEngine

The schema doc specifies the **file format only**. These are not derivable from it:

- **The actual feed URL** — `PROPERTYENGINE_FEED_URL` ships blank. The observed
  live URL was a per-agency Cloud Functions endpoint with an embedded token
  redirecting to Firebase Storage; that is evidence of the *shape*, not a URL we
  can assume applies to us.
- **Whether authorization is enabled for us**, and which scheme — the optional
  `PROPERTYENGINE_FEED_AUTH_TOKEN` (bearer/basic) covers it; unset if the URL
  token is the credential.
- **The pull schedule / mechanism** — no delta endpoint is documented; the adapter
  assumes full-resend-on-every-pull. Nothing wires a cron.
- **Which format they serve us** — doc says JSON, observed feed is XML; the adapter
  handles both, so this is a confirmation, not a blocker.
- **Scope** — one agency's book, or a multi-agency stream. Changes nothing in the
  code, changes what `agencies` ends up holding.
