# PropCtrl field mapping — verified vs. deliberately unmapped

Source of truth: the OpenAPI 3.0.4 spec at `<base>/v1-listing/swagger.json`
(**PropCtrl Listing Service v1**), cross-checked against real API responses. The
production and `api.exdev.propctrl-test.com` copies of the spec are byte-identical
apart from `servers[0].url`.

## The contract

- **Auth** — HTTP Basic on every request: `Authorization: Basic base64(username:password)`
  (or blank username + an API key as the password). No OAuth, no session token,
  nothing to renew. `GET /listing/v1/admin/echo-authenticated` is the credential
  probe (`GET /listing/v1/admin/echo` needs no auth).
- **Feed model — delta, not paginated.**
  1. `GET /listing/v1/listings/changes?fromDate=<ISO-8601>` →
     `{ items: [ { id, changeType: New|Modified|Removed, status, changeDate,
     listingNumber, listingUrl } ], nextFromDate }`. `nextFromDate` is the cursor
     for the next run; there is no page parameter.
  2. `GET /listing/v1/listings?listingIds=…` → `Listing[]`, **max 10 ids**
     (11 → `400 {"errorMessage":"listingIds must be 10 items or less"}`).
  3. `GET /listing/v1/{suburbs|agencies|branches|agents}?{…}Ids=…` — by id, no
     10-id cap.

## Mapped (verified against real records)

| importer field | PropCtrl source |
| --- | --- |
| `vendor_listing_id` | `listingId` |
| `vendor_listing_type` | `"listing"` (single stream) |
| `listing_type` | `mandateType` (`Sale` / `Rental`) — this *is* the type, no inference |
| `property_type` | `propertyType` enum, de-camel-cased (`FlatApartment` → `Flat Apartment`) |
| `title` / `description` | `marketingHeading` / `marketingDescription` |
| `price` | `listPrice` |
| `price_on_application` | `pricingOption ∈ {POA, POAunderAuction}` |
| `bedrooms` / `bathrooms` / `garages` / `parking_spaces` | sum of `features[].value` where `type` is `Bedroom` / `Bathroom` / `Garage` / `Parking` (one entry per room; `0.5` for a half-bath; a parking entry can carry a bay count) |
| `erf_size` / `floor_size` | `erfSize` / `floorArea` `.size`, converted to m² from `measurementUnit` (`Hectare` ×10 000, `Acre` ×4046.8564224) |
| `levies` / `rates_and_taxes` | `levy` / `rates` |
| `street_address` | `doorNumber` + `streetName`, else `location.address` |
| `complex_name` | `estateName` |
| `unit_number` | `doorNumber` |
| `latitude` / `longitude` | `location.latitude` / `.longitude` (present when `showLocation` is true) |
| `features` | `features[].options[].description` + true boolean amenity flags (`solarPanel`, `borehole`, …), de-duplicated |
| `primary_image_url` | first `images[].url` (a real `server.propctrl.com/Image.ashx` URL) |
| `suburb` | `suburbId` → `GET /listing/v1/suburbs` → `suburbName` |
| `agency_vendor_id` / `agency_name` | `agencyId` / agency lookup `name` |
| `agent_vendor_id` / `agent_name` | `agentIds[0]` / agent lookup `firstName + lastName` |
| `listed_at` / `vendor_updated_at` | `created` / `updated` |
| `raw_data.propctrl_*` | `listingNumber`, `listingStatus`, `pricingOption`, `ownershipType`, `furnishedType`, `leasePeriod`, `expires`, `branchId`/`branchName`, full `agentIds`, suburb `city`/`province`/`postalCode`, image count, `commercialInfo`, `farmInfo`, the `changeType` |

## Deliberately not mapped

1. **`internalRemarks`** — the agency's private notes. Excluded from the record
   and from `raw_data` on purpose, not by oversight.
2. **`PUT /listing/v1/listings/{listingId}`** — the status write-back half of the
   partner protocol (report `Active` / `Withdrawn` / `Incomplete` / `Error` back
   to PropCtrl). Contract understood, not implemented: it is a write to a live
   third-party production system.
3. **`Removed` change items** — skipped and counted, never imported. The Step 14
   importer has no withdraw path; disappearance is handled by the `last_seen_at`
   refresh plus the nightly `iol-expire-listings` sweep.
4. **Non-`Active` `listingStatus`** (`Cancelled` / `Withdrawn` / `Expired` /
   `Pending` / `Rented` / `Sold`) — skipped and counted. Only `Active` reaches
   `listings`.
5. **`pricingOption ∈ {PerM2, PerDay, PerWeek, PerYear, Auction}`** — `listPrice`
   is then a rate or a non-monthly period, not a comparable price. Stored as-is
   with the option in `raw_data`; the portal has no column for the pricing basis.
6. **`expires`** — PropCtrl's own expiry date. Not written to `listings.expires_at`,
   which `trg_listings_set_expiry` computes from `feed_sources.ttl_days`. Kept in
   `raw_data`.
7. **`commercialInfo` (~35 fields) / `farmInfo` (9 fields)** — gross/net price,
   gross lettable area, roof & eave heights, dock levellers, farming type, water
   source, … No target columns. Preserved verbatim in `raw_data`, not flattened.
8. **`showDays` / `options` / `propertyDescriptionAndLifeStyleOptions`** — empty
   in every sampled listing; no target columns. Dropped.
9. **Suburb disambiguation** — `resolve_suburb` matches on name then
   `alternate_names`. PropCtrl also supplies `city` / `province` / `postalCode`
   that could disambiguate duplicate suburb names, but the importer takes no such
   parameter; an unresolved suburb already imports with `suburb_id` NULL.
10. **`agentIds` beyond the first** — the schema is a collection; `listings`
    holds one `agent_id`. First agent wins; the full list is kept in `raw_data`.
11. **`matterportUrl` / `youTubeVideoUrl` / `eyeSpyUrl` / `floorPlanImages`** —
    media beyond `primary_image_url` has no home in Domain 4.
12. **An unrecognised `measurementUnit`** — `_area_sqm` returns `None` rather than
    assume m². Only `Metresquared` / `Hectare` / `Acre` exist in the enum today.
