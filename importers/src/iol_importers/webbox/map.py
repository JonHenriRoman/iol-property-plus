"""Map a Webbox :class:`~iol_importers.webbox.parse.Property` to the Step 14
``import_listings`` contract. Pure — no I/O, no DB.

Webbox specifics codified here:

* **``price/currency`` must be ``ZAR``.** Step 14 has no per-listing currency
  column, so a non-ZAR price silently stored as ZAR is wrong — a non-ZAR listing
  is rejected (``__validation_error__``), with the raw currency kept in
  ``raw_data.webbox_currency``. ``price/periodicity`` (Rent only) is not required.
* **``location/country`` is not hardcoded.** It is kept in
  ``raw_data.webbox_country``; a non-``South Africa`` value is imported anyway
  (suburb just will not resolve) and the adapter tallies it.
* **``price/amount`` empty / ``0`` / absent -> price-on-application.**
* **``land-size`` -> ``erf_size``, ``property-size`` -> ``floor_size``**, each via
  :func:`~iol_importers.webbox.features.size_to_sqm` on the vendor's own unit
  string. Either may appear on Sale or Rent; both optional.
* **``<features>`` is a free-form bag** — :func:`parse_features` routes
  ``bedrooms`` / ``bathrooms`` (decimal) / ``garages`` / ``taxes`` to columns and
  captures anything else.
* **Multiple ``<agent>``** — the first drives ``agent_vendor_id`` /
  ``agent_name`` (Step 14 stores one agent); the full ordered roster is kept in
  ``raw_data.webbox_agents``. Rich agency/agent contact fields reach the canonical
  tables through :mod:`iol_importers.webbox.reference`.
* **No date field of any kind** -> ``listed_at`` is left NULL.
* ``description`` keeps its embedded ``Availability: YYYY-MM-DD`` / ``Deposit R…``
  free text verbatim — never extracted.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .features import parse_features, size_to_sqm
from .parse import Property

# Webbox `property-type` -> seeded property_types.name. Values that name-match a
# seeded row (`House`, `Townhouse`, `Farm`, `Apartment`) are omitted and self-map
# via resolve_property_type's ILIKE fallback. An unmapped value passes through
# raw so resolve_property_type quarantines the record.
_PROPERTY_TYPE: dict[str, str] = {
    "studio apartment": "Apartment",
    "cottage": "Apartment",
    "vacant land / plot": "Vacant Land",
    "vacant land": "Vacant Land",
    "plot": "Vacant Land",
}

# Scalar <property> leaf tags consumed by columns / explicit raw_data aliases;
# everything else in prop.fields falls to raw_data under webbox_<tag>.
_PROMOTED_FIELDS = frozenset(
    {"reference", "heading", "description", "property-type", "listing-type", "address"}
)
_EXPLICIT_RAW = frozenset({"featured", "link", "auto-generated-tag", "virtual-tour"})

_TITLE_MAX = 160
_TRUE = frozenset({"t", "true", "yes", "y", "1"})


def _clean(raw: str | None) -> str | None:
    return raw.strip() if raw and raw.strip() else None


def _n(nested: dict[str, dict[str, str]], block: str, key: str) -> str | None:
    return _clean(nested.get(block, {}).get(key))


def _is_poa(amount: str | None) -> bool:
    text = (amount or "").strip()
    if not text:
        return True
    try:
        return Decimal(text) == 0
    except InvalidOperation:
        return False


def _title(prop: Property, property_type: str | None, suburb: str | None) -> str | None:
    heading = _clean(prop.fields.get("heading"))
    if heading:
        return heading[:_TITLE_MAX].rstrip()
    if property_type and suburb:
        return f"{property_type} in {suburb}"
    return None


def _agent_roster(prop: Property) -> list[dict[str, str | None]]:
    roster: list[dict[str, str | None]] = []
    for a in prop.agents:
        entry = {
            "agent_id": _clean(a.get("agent-id")),
            "firstname": _clean(a.get("firstname")),
            "lastname": _clean(a.get("lastname")),
            "name": _clean(a.get("name")),
            "email": _clean(a.get("email")),
            "cellphone": _clean(a.get("cellphone")),
            "landline": _clean(a.get("landline")),
            "bio": _clean(a.get("bio")),
            "branch": _clean(a.get("branch")),
            "agent_image_url": _clean(a.get("agent-image-url")),
        }
        if any(entry.values()):
            roster.append(entry)
    return roster


def _raw_data(prop: Property, roster: list[dict[str, str | None]]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for tag, value in prop.fields.items():
        if tag in _PROMOTED_FIELDS or not value:
            continue
        if tag == "auto-generated-tag":
            raw["webbox_auto_tag"] = value
        elif tag == "link":
            raw["webbox_link"] = value
        elif tag not in _EXPLICIT_RAW:
            raw[f"webbox_{tag.replace('-', '_')}"] = value

    featured = (prop.fields.get("featured") or "").strip().lower()
    if featured:
        raw["webbox_featured"] = featured in _TRUE

    for block, dest in (
        (("price", "currency"), "webbox_currency"),
        (("price", "periodicity"), "webbox_periodicity"),
        (("location", "country"), "webbox_country"),
    ):
        value = _n(prop.nested, block[0], block[1])
        if value:
            raw[dest] = value

    if prop.videos:
        raw["webbox_videos"] = list(prop.videos)
    if prop.agency:
        raw["webbox_agency"] = {k: v for k, v in prop.agency.items() if v}
    if roster:
        raw["webbox_agents"] = roster

    for tag, value in parse_features(prop.features).extra.items():
        raw[f"webbox_feature_{tag.replace('-', '_')}"] = value
    return raw


def to_import_record(prop: Property) -> tuple[dict[str, Any], list[str]]:
    """Return ``(record, image_urls)``."""
    reference = (prop.fields.get("reference") or "").strip()
    type_raw = (prop.fields.get("property-type") or "").strip()
    property_type = _PROPERTY_TYPE.get(type_raw.lower(), type_raw or None)
    suburb = _n(prop.nested, "location", "suburb")
    amount = _n(prop.nested, "price", "amount")
    parsed = parse_features(prop.features)
    roster = _agent_roster(prop)
    primary = roster[0] if roster else {}
    title = _title(prop, property_type, suburb)

    agent_name = " ".join(
        p for p in (primary.get("firstname"), primary.get("lastname")) if p
    ) or primary.get("name")

    record: dict[str, Any] = {
        "vendor_listing_id": reference,
        "title": title,
        "description": _clean(prop.fields.get("description")),
        "property_type": property_type,
        "listing_type": _clean(prop.fields.get("listing-type")),
        "price": None if _is_poa(amount) else amount,
        "price_on_application": _is_poa(amount),
        "floor_size": size_to_sqm(
            _n(prop.nested, "property-size", "property-size-value"),
            _n(prop.nested, "property-size", "property-size-unit"),
        ),
        "erf_size": size_to_sqm(
            _n(prop.nested, "land-size", "land-size-value"),
            _n(prop.nested, "land-size", "land-size-unit"),
        ),
        "street_address": _clean(prop.fields.get("address")),
        "suburb": suburb,
        "latitude": _n(prop.nested, "coordinates", "latitude"),
        "longitude": _n(prop.nested, "coordinates", "longitude"),
        "agency_vendor_id": _clean(prop.agency.get("id")),
        "agency_name": _clean(prop.agency.get("name")),
        "agent_vendor_id": primary.get("agent_id"),
        "agent_name": agent_name,
        "features": parsed.labels,
        "primary_image_url": prop.images[0] if prop.images else None,
    }
    record.update(parsed.columns)
    record.update(_raw_data(prop, roster))

    currency = (record.get("webbox_currency") or "ZAR").strip().upper()
    if not reference:
        record["__validation_error__"] = "reference (vendor_listing_id) is missing"
    elif currency != "ZAR":
        record["__validation_error__"] = (
            f"non-ZAR currency {currency!r} for reference {reference} "
            "(price cannot be stored correctly)"
        )
    elif not title:
        record["__validation_error__"] = (
            f"no usable title for reference {reference} "
            "(heading empty and property_type+suburb not both present)"
        )

    return record, list(prop.images)
