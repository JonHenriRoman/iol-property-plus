"""Map one MyRoof :class:`~iol_importers.bracket_kv.BracketRecord` to the Step 14
``import_listings`` contract. Pure — no I/O, no DB.

MyRoof specifics codified here:

* ``Description`` carries literal ``<p>`` / ``</p>`` / ``<br>`` tags as paragraph
  breaks — :func:`_clean_description` turns them into newlines and unescapes
  entities; a raw ``<p>`` never reaches ``listings.description``.
* ``GPS`` is one ``"lat,lng"`` string; the real "not supplied" sentinel is a bare
  comma (both sides empty) — :func:`_split_gps` returns ``(None, None)`` for it.
* ``Price`` missing **or** ``0`` means price-on-application.
* ``Type`` is crosswalked to the seeded ``property_types``; an unmapped value
  (e.g. ``Guest House``) passes through raw so the importer's
  ``resolve_property_type`` raises ``MappingError`` and the record is quarantined,
  never silently defaulted.
* ``Agent_Name`` is a lender/repossession-program label, not a person — it is
  used as the agent's name (that is what the feed calls the seller) and also kept
  in ``raw_data.myroof_agent_program``. The whole feed is repossessed stock, so
  every record also gets a synthetic ``Repossession`` feature.
* ``Kitchens`` is a plain integer count here (unlike RT3's underscore-wrapped
  list) — it is passed straight through to ``raw_data``, not parsed.

Every key that is not promoted to a column is captured under ``myroof_<Key>`` in
``raw_data`` (a list when the key repeats, e.g. ``Video_URL``).
"""

from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from iol_importers.bracket_kv import BracketRecord

# MyRoof `Type` -> seeded property_types.name (listings/_scratch.py). An unmapped
# value is passed through unchanged for resolve_property_type to reject.
_PROPERTY_TYPE: dict[str, str] = {
    "house": "House",
    "freehold residence": "House",
    "apartment": "Apartment",
    "open plan bachelor/studio apartment": "Apartment",
    "complex": "Townhouse",
    "plot": "Vacant Land",
    "agricultural": "Farm",
    "commercial": "Commercial",
    # "Guest House" left unmapped on purpose — ambiguous fit, becomes a counted
    # mapping error rather than a guess.
}

# `Yes` / `1` booleans -> a human feature label.
_FLAG_FEATURES: tuple[tuple[str, str], ...] = (
    ("Garden", "Garden"),
    ("Staff_Accomm", "Staff Accommodation"),
    ("Pool", "Pool"),
)
_TRUE = frozenset({"yes", "y", "true", "1"})

# Keys consumed by typed columns / features — everything else falls to raw_data.
_PROMOTED_KEYS: frozenset[str] = frozenset(
    {
        "Reference",
        "Heading",
        "Description",
        "Type",
        "Status",
        "Price",
        "Beds",
        "Baths",
        "Garages",
        "Building_Size",
        "Erf_Size",
        "Address",
        "Suburb",
        "GPS",
        "Branch_ID",
        "Branch_Name",
        "Email",
        "Image_URL",
        "Agent_Name",
        "Garden",
        "Staff_Accomm",
        "Pool",
        "Listed",
    }
)

_PARA_TAG = re.compile(r"</?p\b[^>]*>|<br\b[^>]*/?>", re.IGNORECASE)
_TRAILING_WS = re.compile(r"[ \t]+\n")
_BLANK_RUN = re.compile(r"\n{3,}")


def _clean_description(raw: str | None) -> str | None:
    if not raw:
        return None
    text = _PARA_TAG.sub("\n", raw)
    text = html.unescape(text)
    text = _TRAILING_WS.sub("\n", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip() or None


def _split_gps(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return (None, None)
    parts = raw.split(",")
    if len(parts) < 2:
        return (None, None)
    lat, lng = parts[0].strip(), parts[1].strip()
    return (lat or None, lng or None)


def _is_poa(price: str) -> bool:
    if not price:
        return True
    try:
        return Decimal(price) == 0
    except InvalidOperation:
        return False


def _features(rec: BracketRecord) -> list[str]:
    labels = [
        label for key, label in _FLAG_FEATURES if (rec.get(key) or "").strip().lower() in _TRUE
    ]
    labels.append("Repossession")  # the whole MyRoof feed is repossessed stock
    return labels


def _raw_data(rec: BracketRecord) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key, values in rec.as_dict().items():
        if key in _PROMOTED_KEYS or not values:
            continue
        raw[f"myroof_{key}"] = values[0] if len(values) == 1 else values

    agent_program = rec.get("Agent_Name")
    if agent_program:
        raw["myroof_agent_program"] = agent_program
    _aliases = (
        ("Status", "myroof_status"),
        ("Type", "myroof_type"),
        ("GPS", "myroof_gps_raw"),
    )
    for key, dest in _aliases:
        value = rec.get(key)
        if value:
            raw[dest] = value
    return raw


def to_import_record(rec: BracketRecord) -> tuple[dict[str, Any], list[str]]:
    """Return ``(record, image_urls)``."""
    reference = (rec.get("Reference") or "").strip()
    heading = (rec.get("Heading") or "").strip()
    type_raw = (rec.get("Type") or "").strip()
    price = (rec.get("Price") or "").strip()
    lat, lng = _split_gps(rec.get("GPS"))
    images = [u for u in rec.get_all("Image_URL") if u.strip()]

    record: dict[str, Any] = {
        "vendor_listing_id": reference,
        "title": heading or None,
        "description": _clean_description(rec.get("Description")),
        "property_type": _PROPERTY_TYPE.get(type_raw.lower(), type_raw or None),
        "listing_type": (rec.get("Status") or "").strip() or None,
        "price": None if _is_poa(price) else price,
        "price_on_application": _is_poa(price),
        "bedrooms": (rec.get("Beds") or "").strip() or None,
        "bathrooms": (rec.get("Baths") or "").strip() or None,
        "garages": (rec.get("Garages") or "").strip() or None,
        "floor_size": (rec.get("Building_Size") or "").strip() or None,
        "erf_size": (rec.get("Erf_Size") or "").strip() or None,
        "street_address": (rec.get("Address") or "").strip() or None,
        "suburb": (rec.get("Suburb") or "").strip() or None,
        "latitude": lat,
        "longitude": lng,
        "agency_vendor_id": (rec.get("Branch_ID") or "").strip() or None,
        "agency_name": (rec.get("Branch_Name") or "").strip() or None,
        "agent_vendor_id": (rec.get("Email") or "").strip().lower() or None,
        "agent_name": (rec.get("Agent_Name") or "").strip() or None,
        "features": _features(rec),
        "primary_image_url": images[0] if images else None,
        "listed_at": (rec.get("Listed") or "").strip() or None,
    }
    record.update(_raw_data(rec))

    if not reference:
        record["__validation_error__"] = "Reference (vendor_listing_id) is missing"
    elif not heading:
        record["__validation_error__"] = f"Heading (title) is missing for Reference {reference}"

    return record, images
