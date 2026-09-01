# Webbox feed — mapping notes

Source: one XML file per site at
`{domain}/template/feeds,WebboxFeedForSite.vm/siteid/{siteid}/securitykey/{securitykey}/feed.xml`
— a plain GET where **the URL itself is the credential**. Stream-parsed with
stdlib `xml.etree.ElementTree.iterparse` (no lxml). Full resend, no delta, no
delete signal — absences are reconciled with `lifecycle.withdraw.withdraw_missing`.

## Outer XML structure (confirmed)

The sibling Go pack's real production captures (21 and 411 properties) confirm:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE agencies SYSTEM "http://property2.webbox.co.za/adminImages/webboxFeed.dtd">
<agencies>
  <agency>
    <agency-details> id, name, logo-url, email, landline, cellphone,
                     head-office-location </agency-details>
    <properties>
      <property>…</property>
      <property>…</property>
    </properties>
  </agency>
</agencies>
```

The repeated `<property>` nests **two levels inside `<agency>`**, beside that
agency's `<agency-details>`. `parse.py` walks `end` events keyed on tag name, so
it also accepts a bare `<property>` document root and a consecutive stream of
`<property>` elements — `ParseResult.outer_form` (`wrapped` / `bare-property` /
`streamed`) reports which was actually seen, and it is surfaced on every run
result. The `<!DOCTYPE … SYSTEM …>` declaration is ignored by stdlib ET (no
external fetch, no XXE); CDATA is returned transparently; an empty `<amount/>` /
`<virtual-tour/>` yields `""`.

## Per-site configuration

The URL is the credential, so the per-site values are the **domain** (`base_url`)
and the **`siteid` + `securitykey`** pair (`auth_config`) — never in the source
tree, an env var, a log line, or the run result:

```sql
INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
VALUES ('webbox-valuables', 'Valuables Properties (Webbox)', 'Webbox',
        'https://www.valuablesproperties.co.za',
        '{"siteid": "612", "securitykey": "<opaque key>"}');
```

`WEBBOX_FEED_URL_TEMPLATE` (optional, in `.env.example` / `src/server/env.ts`)
overrides only the shared URL path template.

## Listing field mapping

| record key | Webbox source | note |
| --- | --- | --- |
| `vendor_listing_id` | `reference` | blank → counted validation reject |
| `title` | `heading` | CDATA; blank → `"{property_type} in {suburb}"`, tallied |
| `description` | `description` | CDATA; kept verbatim incl. the embedded `Availability: YYYY-MM-DD` / `Deposit R…` free text |
| `property_type` | `property-type` → crosswalk | `Studio apartment`/`Cottage` → Apartment, `Vacant Land / Plot` → Vacant Land, rest self-map; unmapped → `MappingError` quarantine |
| `listing_type` | `listing-type` | `Sale` / `Rent` |
| `price` / `price_on_application` | `price/amount` | empty `<amount/>` **or** `0` **or** absent → POA |
| `bedrooms` / `bathrooms` / `garages` | `features/*` | `bathrooms` is a real decimal (`4.5`) |
| `rates_and_taxes` | `features/taxes` | the municipal-rates equivalent; no `levy` field exists |
| `floor_size` | `property-size/property-size-value` + `-unit` | `features.size_to_sqm` |
| `erf_size` | `land-size/land-size-value` + `-unit` | `features.size_to_sqm`; either block may appear on Sale or Rent, both optional |
| `street_address` | `address` | CDATA |
| `suburb` | `location/suburb` | name-matched, NULL if unresolved |
| `latitude` / `longitude` | `coordinates/latitude` `/longitude` | optional element |
| `agency_vendor_id` / `agency_name` | `agency-details/id` `/name` | from the property's `<agency>`; absent → NULL agency (bare-property samples) |
| `agent_vendor_id` / `agent_name` | first `agents/agent/agent-id` / `firstname`+`lastname` | see co-agents |
| `features` | unknown `features/*` tags with a `Yes` value | importer dedupes to `text[]` |
| `primary_image_url` | first `images/image` | repeated leaf elements, text is the URL |
| `listed_at` | — | **Webbox has no date field of any kind** → NULL |

### Size units (`features.size_to_sqm`)

Case-insensitive: `meters_squared` / `m2` / `sqm` → ×1, `hectares` / `ha` →
×10000, `acres` / `ac` → ×4046.8564224. A missing/unknown unit defaults to
`meters_squared`. A value that overflows `numeric(10,2)` after conversion is
dropped (kept in `raw_data` instead).

## Validated, not assumed

| Field | Sample value | Rule |
| --- | --- | --- |
| `price/currency` | `ZAR` | Step 14 has no per-listing currency column, so a non-`ZAR` price stored as `ZAR` is wrong → **the listing is rejected** (`__validation_error__`, counted). Raw currency always kept in `raw_data.webbox_currency`; `non_zar_rejected` on the run result. |
| `location/country` | `South Africa` | A non-`South Africa` value is **imported** (suburb simply will not resolve); `raw_data.webbox_country` always kept; every country value is tallied on the run result. |

## Agency / agent enrichment (`reference.py`)

Webbox carries rich contact data, so — like AllSA / Fusion — a dedicated
`reference.py` upsert runs **before** `import_listings`:

- `upsert_agency` keyed on `agency_vendor_ids (feed_source_id, agency-details/id)`
  → writes `name`, `email`, `phone` (← `landline`), `website` (← `logo-url`).
- `upsert_agent` keyed on `agent_vendor_ids (feed_source_id, agent-id)` →
  `split_person_name` from `firstname`+`lastname`, writes `display_name`,
  `email`, `phone` (← `landline`), `mobile` (← `cellphone`).

## Co-agents

`agents/agent[]` is 1..N. Step 14 stores one `agent_id`, so the **first** agent
drives `agent_vendor_id` / `agent_name` (and the `reference.py` link); the **full
ordered roster** `[{agent_id, firstname, lastname, email, cellphone, landline,
bio, branch, agent_image_url}, …]` goes to `raw_data.webbox_agents`.

## raw_data

`webbox_<tag>` for every scalar `<property>` child not promoted, plus explicit
`webbox_currency`, `webbox_periodicity` (Rent only), `webbox_country`,
`webbox_featured` (bool), `webbox_auto_tag` (= `auto-generated-tag`),
`webbox_link`, `webbox_videos` (list), `webbox_agents` (roster),
`webbox_agency` (the full `agency-details`), and `webbox_feature_<tag>` for
unknown `<features>` children.

## Deliberately not mapped / caveats

* **No structured rental fields** — deposit / lease-term / furnished / pets are
  all real but only ever appear as free text inside `<description>` (e.g.
  `Deposit R37500`). Never extracted.
* **`videos` / `virtual-tour`** → `raw_data.webbox_videos` /
  `raw_data.webbox_virtual_tour`. Promoting a `<video-url>` to a `listing_media`
  video row is a follow-up, not this step.
* **`auto-generated-tag`** is Webbox's own SEO title, redundant with `heading` —
  kept in `raw_data`, not authoritative.
* **No DTD validation** — stdlib ET ignores the `<!DOCTYPE … SYSTEM …>`; vendor
  conformance is assumed, as for every other feed in this pipeline.

## Parser

`iol_importers.webbox.parse` — stdlib `xml.etree.ElementTree.iterparse` over
`end` events. Streams the document (the objective's "stream-parse if large" ask,
met without a new dependency); duplicate `<features>` children are dropped
first-wins with a tally.
