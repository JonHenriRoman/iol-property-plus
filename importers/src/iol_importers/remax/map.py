"""Map a RE/MAX property object to the ``import_listings`` record contract.

The input is a full RE/MAX property (``/listing`` or ``/agents-page``). Controlled
vocabularies (``listing_type``, ``property_type``) are mapped through explicit
dicts, never inferred. Fields whose meaning is unclear or which have no column are
recorded in ``MAPPING_NOTES.md`` and kept in ``raw_data``.
"""

from __future__ import annotations

import re
from typing import Any

# property_type: match the base segment (before the first ':'). RE/MAX sends
# "Vacant Land / Plot: residential", "Commercial Property: Hotel", "House", etc.
_PROPERTY_TYPE: dict[str, str] = {
    "House": "House",
    "Apartment / Flat": "Apartment",
    "Townhouse": "Townhouse",
    "Vacant Land / Plot": "Vacant Land",
    "Farm": "Farm",
    "Commercial Property": "Commercial",
    "Industrial Property": "Industrial",
}

# listing_type: the doc's controlled vocabulary. Anything else -> the importer's
# normalize_listing_type will land it on 'Unknown'.
_LISTING_TYPE: dict[str, str] = {
    "For Sale": "For Sale",
    "To Rent": "To Rent",
}

# features.* boolean-string flags worth surfacing in listings.features[].
_FLAG_LABELS: dict[str, str] = {
    "access_gate": "Access Gate",
    "aircon": "Air Conditioning",
    "alarm_system": "Alarm System",
    "balcony": "Balcony",
    "bore_hole": "Borehole",
    "built_in_braai": "Built-in Braai",
    "study": "Study",
    "patio": "Patio",
    "pool": "Pool",
    "deck": "Deck",
    "spa_bath": "Spa Bath",
    "gym": "Gym",
    "golf_course": "Golf Course",
    "club_house": "Club House",
    "squash_court": "Squash Court",
    "tennis_court": "Tennis Court",
    "staff_quarters": "Staff Quarters",
    "laundry": "Laundry",
    "storage": "Storage",
    "walk_in_closet": "Walk-in Closet",
    "built_in_cupboards": "Built-in Cupboards",
    "wheelchair_friendly": "Wheelchair Friendly",
    "tv": "TV",
    "satellite": "Satellite",
    "pets_allowed": "Pets Allowed",
    "fence": "Fence",
    "security_post": "Security Post",
    "scenic_view": "Scenic View",
    "sea_view": "Sea View",
    "kitchen": "Kitchen",
    "lapa": "Lapa",
    "electric_fencing": "Electric Fencing",
    "fire_place": "Fireplace",
    "garden_cottage": "Garden Cottage",
    "jetty_berth": "Jetty / Berth",
    "scullery": "Scullery",
    "pantry": "Pantry",
    "guest_toilet": "Guest Toilet",
    "enterance_hall": "Entrance Hall",
    "irrigation_system": "Irrigation System",
    "paving": "Paving",
    "intercom": "Intercom",
    "family_tv_room": "Family TV Room",
}

_RAW_FEATURE_INTS = ("num_en_suite", "lounges", "dining_rooms", "flatlets", "storys")


def _clean_description(value: object) -> str | None:
    text = _cdata(value)
    return strip_html(text) or None if text else None


def _cdata(value: object) -> str | None:
    """Unwrap RE/MAX's ``{"_cdata": "…"}`` (or a bare string)."""
    if isinstance(value, dict):
        value = value.get("_cdata")
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "undefined", "none"}:
        return None
    return text


def _s(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _num(value: object) -> object:
    """Pass numbers / numeric strings straight to the importer; drop blanks & zeros-as-unknown."""
    if value in (None, "", "0", 0):
        return None
    return value


def _geo(raw: dict[str, Any], key: str) -> object:
    geo = raw.get("geo_location") or {}
    value = str(geo.get(key, "")).strip()
    if not value or value in {"0", "0.0", "0.000000"}:
        return None
    return value


def _property_type(raw_value: object) -> tuple[str | None, str | None]:
    """(canonical property_type, subtype-or-junk suffix for raw_data)."""
    text = _s(raw_value)
    if text is None:
        return None, None
    base, _, subtype = text.partition(":")
    return _PROPERTY_TYPE.get(base.strip()), (subtype.strip() or None)


def _feature_list(features: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key, label in _FLAG_LABELS.items():
        if str(features.get(key, "")).strip().lower() == "true":
            out.append(label)
    for chunk in str(features.get("custom_features") or "").split(","):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return list(dict.fromkeys(out))


def _primary_image(raw: dict[str, Any]) -> str | None:
    photos = (raw.get("photos") or {}).get("photo") or []
    active = [p for p in photos if str(p.get("active", "true")).lower() == "true" and p.get("url")]
    active.sort(key=lambda p: p.get("order", 0))
    return active[0]["url"] if active else None


def _street_address(raw: dict[str, Any]) -> str | None:
    addr = raw.get("address") or {}
    parts = [_s(addr.get("street_number")), _s(addr.get("street_name"))]
    return " ".join(p for p in parts if p) or None


def _agent_name(agent: dict[str, Any]) -> str | None:
    parts = [_s(agent.get("first_name")), _s(agent.get("surname")) or _s(agent.get("last_name"))]
    return " ".join(p for p in parts if p) or None


def _media_urls(raw: dict[str, Any]) -> list[str]:
    media = raw.get("media") or {}
    out = []
    for block in media.values():
        if isinstance(block, dict):
            out.extend(v for v in block.values() if isinstance(v, str) and v)
    return out


def to_import_record(
    raw: dict[str, Any],
    *,
    agent: dict[str, Any] | None = None,
    office: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = raw.get("features") or {}
    agent = agent or raw.get("_remax_agent") or _first_agent(raw)
    office = office or raw.get("_remax_branch") or raw.get("office") or {}

    property_type, subtype = _property_type(raw.get("property_type"))
    covered = features.get("covered_parkings") or 0
    open_p = features.get("open_parkings") or 0
    parking = (covered or 0) + (open_p or 0)

    office_id = office.get("office_id") or office.get("branch_id")

    record: dict[str, Any] = {
        "vendor_listing_id": str(raw["property_id"]),
        "vendor_listing_type": "listing",
        "listing_type": _LISTING_TYPE.get(
            _s(raw.get("listing_type")) or "", raw.get("listing_type")
        ),
        "property_type": property_type,
        "title": _cdata(raw.get("heading")) or _s(raw.get("marketing_header")),
        "description": _clean_description(raw.get("description")),
        "price": _num((raw.get("price") or {}).get("amount")),
        "price_on_application": bool((raw.get("price") or {}).get("poa")),
        "bedrooms": _num(features.get("bedrooms")),
        "bathrooms": _num(features.get("bathrooms")),
        "garages": _num(features.get("garages")),
        "parking_spaces": parking or None,
        "erf_size": _num(features.get("erf_size")),
        "floor_size": _num(features.get("floor_size")),
        "levies": _num(features.get("levy")),
        "rates_and_taxes": _num(features.get("rates")),
        "street_address": _street_address(raw),
        "latitude": _geo(raw, "latitude"),
        "longitude": _geo(raw, "longitude"),
        "suburb": _cdata((raw.get("location") or {}).get("suburb")),
        "features": _feature_list(features),
        "primary_image_url": _primary_image(raw),
        "agency_vendor_id": str(office_id) if office_id is not None else None,
        "agency_name": _s(office.get("name")),
        "agent_vendor_id": str(agent.get("agent_id"))
        if agent.get("agent_id") is not None
        else None,
        "agent_name": _agent_name(agent),
        "listed_at": _s(raw.get("published_datetime")),
        "vendor_updated_at": _s(raw.get("date_last_updated")),
        # --- not promoted: copied verbatim into listings.raw_data -----------
        "remax_reference": _s(raw.get("reference")),
        "remax_listing_state": _s(raw.get("listing_state")),
        "remax_mandate_type": _s(raw.get("mandate_type")),
        "remax_price_periodicity": _s((raw.get("price") or {}).get("periodicity")),
        "remax_property_type_raw": _s(raw.get("property_type")),
        "remax_property_type_subtype": subtype,
        "remax_land_area_units": _s(features.get("land_area_units")),
        "remax_floor_area_units": _s(features.get("floor_area_units")),
        "remax_listing_link": _s(raw.get("listing_link")),
        "remax_photo_count": len((raw.get("photos") or {}).get("photo") or []),
        "remax_media_urls": _media_urls(raw),
        "remax_city": _cdata((raw.get("location") or {}).get("city")),
        "remax_province": _cdata((raw.get("location") or {}).get("province")),
    }
    for key in _RAW_FEATURE_INTS:
        if features.get(key):
            record[f"remax_{key}"] = features[key]
    return record


def _first_agent(raw: dict[str, Any]) -> dict[str, Any]:
    details = (raw.get("agents") or {}).get("agent_details") or []
    return details[0] if details else {}


def strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    collapsed = re.sub(r"\s+", " ", without_tags)
    return re.sub(r"\s+([.,;:!?)])", r"\1", collapsed).strip()
