# Entegral feed — mapping notes

## The contract

Confirmed with Entegral directly (Dillon Gray, 2026-08-13): this is a **pull**
feed, not the push-oriented Sync API published at
`https://api.entegral.net/SyncAPI.html`. Two HTTP Basic-auth `GET` endpoints:

| Endpoint | Returns |
| --- | --- |
| `GET /api/officeslist` | the offices that opted into syndication to us, each with an `officereference` |
| `GET /api/listings?type=officelistings&ref={officereference}` | that office's **complete active** for-sale / rental listings, agent + office contact inline |

The listing shape follows the Sync API `CreateOrUpdateListing` object
(`https://api.entegral.net/SyncAPI.json` — swagger 2.0): flat keys, `"1"`/`"0"`
string booleans, `"-"` / `""` sentinels, `latlng` as one `"lat,lng"` string,
`contact[]` carrying the agent (and only the office *id* — the office *name*
comes from the `officeslist` entry).

The feed updates twice a day; Entegral requires a poll at least every 24 hours.
`entegral-import` is scheduled every 12 hours (`0 */12 * * *`) to catch both.

> **Exact `officeslist` / `officelistings` field names are pinned to a sandbox
> probe.** No Entegral credentials were available at build time. The client
> accepts the obvious spellings of `officereference` / office name; the listing
> mapping follows the swagger `CreateOrUpdateListing` shape. Re-verify on the
> first real run.

> **Plaintext HTTP.** Entegral gave `http://` URLs. The client tries
> `https://sync.entegral.net` first and only drops to `http://` when TLS is
> unreachable, logging a one-line warning. If the fallback ever triggers, raise
> it with Entegral.

## Sync model

`officelistings` is a **full snapshot** of one office's active book — there is no
deletions endpoint. Disappearance is handled by **per-office reconciliation**:
after an office imports cleanly, `lifecycle.withdraw_missing` marks every listing
scoped to that `officereference` (via `raw_data ->> 'entegral_office_reference'`)
whose `clientPropertyID` was absent from the response as `status = 'Withdrawn'`
(soft-delete, never a row removal, idempotent, no migration).

**Guard:** reconciliation is skipped for an office whose response was empty or
whose import had any failure — a transient empty response must never withdraw an
office's whole book. `withdraw_missing` also refuses an empty `seen` set outright.

## Photos — downloaded and re-hosted

Entegral's terms do not permit hyperlinking their images, and `next.config.ts`
sets `images.remotePatterns: []` (deny-all). Every `photos[].imgUrl` is
downloaded, validated by magic bytes (`image/jpeg|png|webp|gif` only — the
vendor `Content-Type` is not trusted), content-addressed on our own storage
(`data/media/entegral/<sha[:2]>/<sha>.<ext>`), and recorded in `listing_media`
with a **site-relative** URL (`/media/entegral/…`). `primary_image_url` is set to
the first re-hosted asset — never a vendor URL. A source-URL index means the
twice-daily poll re-downloads nothing; `--refresh-media` forces a re-fetch. A
single photo failing (404, timeout, oversize > 15 MB, not an image) is logged
and skipped and never fails its listing.

Served by `src/app/media/[...path]/route.ts` from `MEDIA_ROOT_DIR`
(default `<repo>/data/media`). Under Docker that directory needs a mounted
volume — documented in the README under "Not yet implemented", not wired.

## Mapped fields

| importer key | Entegral source |
| --- | --- |
| `vendor_listing_id` | `clientPropertyID` |
| `vendor_listing_type` | `"officelistings"` (constant) |
| `listing_type` | `propertyStatus` → controlled dict (`For Sale` / `Rental *` → `For Sale` / `To Rent`) |
| `property_type` | `propertyType` → controlled dict onto the seeded canonical types; unknown values fall through to `resolve_property_type` |
| `title` | `title`, else `propertyType in suburb` |
| `description` | `description`, HTML stripped |
| `price` / `price_on_application` | `price` / always `false` (POA not in the feed) |
| `bedrooms` / `bathrooms` / `garages` | `beds` / `baths` / `garages` |
| `parking_spaces` | `carports` + `openparking` |
| `erf_size` / `floor_size` | `landSize` (× 10 000 when `landSizeType` = `ha`) / `buildingSize` |
| `levies` / `rates_and_taxes` | `levy` / `ratesAndTaxes` |
| `street_address` | `streetNumber` + `streetName` |
| `complex_name` / `unit_number` | `complexName` / `unitNumber` |
| `latitude` / `longitude` | `latlng` split on `,` (dropped when blank or `0`) |
| `suburb` | `suburb` |
| `features` | `pool` / `petsAllowed` / `flatLet` / `furnished` / `isReduced` flags + the `*Features` freetext fields (comma-split) + `electricalSupply` / `waterSupply` arrays, de-duplicated |
| **`agency_vendor_id` / `agency_name`** | `officereference` / office name from `officeslist` — **required** |
| **`agent_vendor_id` / `agent_name`** | `contact[0].clientAgentID` / `contact[0].fullName` — **required** |
| `listed_at` / `vendor_updated_at` | `listDate` / `timestamp` (`YYYY/MM/DD` → ISO) |
| `raw_data.entegral_*` | `officereference`, `propertyStatus`, `propertyType` (raw), `mandate`, `currency`, `priceUnit`, `town`, `province`, `expiryDate`, `isDevelopment`, `vtUrl`, agent cell/email/profile/logo, office logo, `study` / `livingAreas` / `staffAccommodation`, `files[]`, `photo_count` |

### Agent + office name — a hard requirement

Every rendered Entegral listing must display the agent's name and their office's
name. A listing missing either gets `__validation_error__` set, so
`import_listings` records it in `import_errors` (`error_type = 'validation'`,
raw payload preserved) and **does not import it** — never a silent import
without attribution. Contact details (cell / email) are optional and land in
`raw_data`.

## Deliberately not mapped

1. **`propertyStatus` = `Sold` / `Inactive` / `Pending Sale` / `Auction`** — an
   `officelistings` response is meant to be the *active* set; `Sold`/`Auction`
   map to `For Sale`, `Inactive` falls through to `Unknown`. The raw value is
   kept in `raw_data.entegral_property_status`.
2. **`onshow[]` (show-house times)** — no canonical table wired (same as the
   other feeds). Kept only implicitly via `raw_data` if present.
3. **`files[]` (brochures, external links) and `vtUrl` (virtual tour)** — no
   `listing_media` rows created for non-photo media; URLs kept in `raw_data`.
   Photos are the only re-hosted media type.
4. **`portalListing[]`** — which downstream portals Entegral also syndicates the
   listing to. Not relevant to our import.
5. **`bedroomFeatures` / `bathroomFeatures` / `kitchenFeatures` free text** —
   appended to `features[]` verbatim (comma-split); not parsed into canonical
   amenity names.
6. **`showOnMap`, `isReduced`, `mandate`** — display hints, kept in `raw_data`,
   not promoted.
7. **`currency` / `priceUnit`** — every sandbox listing is `ZAR`; `priceUnit`
   (rental periodicity) is kept in `raw_data.entegral_price_unit` because it
   changes what the rental number means, but there is no typed column for it.
8. **`study` / `livingAreas` / `staffAccommodation` counts** — no `listings`
   columns; kept in `raw_data`.

## Obligations outside this importer

These were stated by Entegral and are **not** in this importer's scope. They are
recorded here and in the root README so whoever builds the relevant feature
honours them.

1. **Lead / enquiry emails.** Any enquiry generated from an Entegral-sourced
   listing must be emailed to the listing's associated agent(s), **and a copy of
   the lead email must go to `support@entegral.net`** for their CRM. No
   lead-email code exists in the repo yet (`enquiries` is a table only); this is
   a requirement on whoever implements enquiry notifications.
2. **No third-party handoff.** Entegral-sourced listing and lead data must not be
   sold or handed off to any third party.
3. **Open decision for the operator (not built).** Entegral separately asked for
   a direct hyperlink pattern to individual listings — e.g.
   `https://oursite.co.za/?ref={clientPropertyID}` — or a reference-pairing flat
   file they can ingest. This is a product/URL-structure decision, deliberately
   left unbuilt. `clientPropertyID` is stored as `listings.vendor_listing_id`,
   so either option is available later without re-importing.
