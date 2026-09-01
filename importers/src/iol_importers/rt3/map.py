"""Map one RT3 (Rawson) :class:`~iol_importers.bracket_kv.BracketRecord` to the
Step 14 ``import_listings`` contract. Pure — no I/O, no DB.

RT3 specifics codified here:

* **Numbered co-agent fields.** ``Agent_Name`` / ``Cell_No`` / ``Email`` for the
  first agent, then ``Agent_Name_2`` / ``Cell_No_2`` / ``Email_2`` … for an
  arbitrary number of further agents. :func:`_agents` builds the ordered roster;
  the first entry drives ``agent_vendor_id`` / ``agent_name`` (Step 14 stores one
  agent per listing) and the whole roster is kept in ``raw_data.rt3_agents``.
* **Hyphenated ``Type`` taxonomy** (``Commercial - Retail``). :data:`_PROPERTY_TYPE`
  crosswalks the values that do not name-match a seeded ``property_types`` row;
  an unmapped value (``Guest House``, ``Unclassified``) passes through raw so
  ``resolve_property_type`` quarantines the record.
* **``Kitchens`` is an underscore-token list** (``_gas hob_, _granite tops_``) —
  unique to RT3 (MyRoof / PropertyPost both use it as a plain count/flag).
  :func:`_kitchen_fittings` parses it to a list into
  ``raw_data.rt3_kitchen_fittings``; it is not a feature and not a count.
* **``Views`` / ``Security`` / ``Balcony`` / ``Patio`` / ``Garden``** are
  comma-separated free-text tag lists, not booleans — every token is folded into
  ``features``. ``Pool`` / ``Alarm`` / ``Laundry`` / ``Staff_Accomm`` /
  ``Ensuites`` are ``Yes``/absent booleans -> a feature label.
* **``Study`` / ``Family_Rooms`` / ``Reception_Rooms`` / ``Levels``** are numeric
  counts with no canonical column -> ``raw_data``, never folded into features.
* **``GPS``** is one ``"lat,lng"`` string; the "no coordinates" sentinel is
  ``"0.00000000,0.00000000"`` (also guard ``"0,0"`` and both-zero).
* **``Status``** (``For Sale`` / ``To Let``) is the listing type, not a lifecycle
  state.

Every key that is not promoted to a column is captured under ``rt3_<Key>`` in
``raw_data`` (a list when the key repeats).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from iol_importers.bracket_kv import BracketRecord

# RT3 `Type` values that do NOT case-insensitively name-match a seeded
# property_types row. `House`, `Cluster`, `Commercial`, `Development`, `Office`,
# `Industrial`, `Farm`, `Vacant Land` all self-map via resolve_property_type's
# ILIKE fallback and are deliberately absent here. `Guest House`,
# `Commercial - Guest House` and `Unclassified` are absent so they quarantine.
_PROPERTY_TYPE: dict[str, str] = {
    "bachelor apartment": "Apartment",
    "bachelor flat": "Apartment",
    "bachelor": "Apartment",
    "flat": "Apartment",
    "loft apartment": "Apartment",
    "duplex apartment": "Apartment",
    "duplex loft": "Apartment",
    "maisonette": "Apartment",
    "penthouse": "Apartment",
    "cottage": "Apartment",
    "block of flats": "Apartment Block",
    "duet": "Townhouse",
    "townhouse - freehold": "Townhouse",
    "townhouse - sectional": "Townhouse",
    "duplex townhouse - freehold": "Townhouse",
    "duplex townhouse - sectional": "Townhouse",
    "smallholding": "Farm",
    "commercial - farm (agricultural holding)": "Farm",
    "vacant erf": "Vacant Land",
    "vacant stand": "Vacant Land",
    "commercial - vacant land": "Vacant Land",
    "commercial - offices": "Office",
    "commercial - factory": "Industrial",
    "commercial - warehouse": "Industrial",
    "commercial - industrial": "Industrial",
    "commercial - commercial property": "Commercial",
    "commercial - conference/wedding venue": "Commercial",
    "commercial - mixed use": "Commercial",
    "commercial - other": "Commercial",
    "commercial - retail": "Commercial",
    "commercial - block of residential flats": "Commercial",
}

# Comma-separated free-text tag lists -> every token folded into features.
_TAG_FIELDS: tuple[str, ...] = ("Views", "Security", "Balcony", "Patio", "Garden")
# `Yes`/absent booleans -> a feature label.
_BOOL_FEATURES: tuple[tuple[str, str], ...] = (
    ("Pool", "Pool"),
    ("Alarm", "Alarm"),
    ("Laundry", "Laundry"),
    ("Staff_Accomm", "Staff Accommodation"),
    ("Ensuites", "En-suite"),
)
_TRUE = frozenset({"yes", "y", "true", "1"})

# Keys consumed by typed columns / features / explicit raw_data aliases.
# Agent-roster keys (Agent_Name*, Cell_No*, Email*) are excluded separately.
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
        "Carports",
        "Building_Size",
        "Erf_Size",
        "Address",
        "Suburb",
        "GPS",
        "Branch_ID",
        "Branch_Name",
        "Listed",
        "Image_URL",
        "Kitchens",
        *_TAG_FIELDS,
        *(key for key, _ in _BOOL_FEATURES),
    }
)

_AGENT_KEY = re.compile(r"^(Agent_Name|Cell_No|Email)(?:_(\d+))?$")
_UNDERSCORE_TOKEN = re.compile(r"_([^_]+)_")
_GPS_SENTINELS = frozenset({"", "0,0", "0.00000000,0.00000000"})
_TITLE_MAX = 120


def _clean(raw: str | None) -> str | None:
    return raw.strip() if raw and raw.strip() else None


def _s(rec: BracketRecord, key: str) -> str | None:
    return (rec.get(key) or "").strip() or None


def _is_poa(price: str) -> bool:
    if not price:
        return True
    try:
        return Decimal(price) == 0
    except InvalidOperation:
        return False


def _split_gps(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return (None, None)
    text = raw.strip()
    if text in _GPS_SENTINELS:
        return (None, None)
    parts = text.split(",")
    if len(parts) < 2:
        return (None, None)
    lat, lng = parts[0].strip(), parts[1].strip()
    if not lat or not lng:
        return (None, None)
    try:
        if Decimal(lat) == 0 and Decimal(lng) == 0:
            return (None, None)
    except InvalidOperation:
        pass
    return (lat, lng)


def _kitchen_fittings(raw: str | None) -> list[str] | None:
    """Parse RT3's ``_extractor fan_, _gas hob_`` list into ordered tokens."""
    if not raw or not raw.strip():
        return None
    tokens = [t.strip() for t in _UNDERSCORE_TOKEN.findall(raw) if t.strip()]
    if tokens:
        return tokens
    return [raw.strip()]  # not the expected shape — keep the value rather than drop it


def _agents(rec: BracketRecord) -> list[dict[str, str | None]]:
    """Ordered roster from the numbered ``Agent_Name`` / ``Cell_No`` / ``Email``
    fields. Index 1 is the unsuffixed set; ``_2``, ``_3`` … follow. Handles zero,
    one, many, and gappy suffix sets."""
    by_index: dict[int, dict[str, str | None]] = {}
    for key in rec.as_dict():
        m = _AGENT_KEY.match(key)
        if not m:
            continue
        field, suffix = m.group(1), m.group(2)
        index = int(suffix) if suffix else 1
        slot = by_index.setdefault(index, {"name": None, "email": None, "cell": None})
        value = _s(rec, key)
        if field == "Agent_Name":
            slot["name"] = value
        elif field == "Email":
            slot["email"] = value
        else:
            slot["cell"] = value
    roster = [by_index[i] for i in sorted(by_index)]
    return [a for a in roster if a["name"] or a["email"] or a["cell"]]


def _features(rec: BracketRecord) -> list[str]:
    out: list[str] = []
    for field in _TAG_FIELDS:
        for token in (rec.get(field) or "").split(","):
            token = token.strip()
            if token:
                out.append(token)
    for key, label in _BOOL_FEATURES:
        if (rec.get(key) or "").strip().lower() in _TRUE:
            out.append(label)
    return list(dict.fromkeys(out))  # dedupe, preserve order


def _raw_data(rec: BracketRecord, province: str) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key, all_values in rec.as_dict().items():
        if key in _PROMOTED_KEYS or _AGENT_KEY.match(key):
            continue
        values = [v for v in all_values if v and v.strip()]
        if not values:
            continue
        raw[f"rt3_{key}"] = values[0] if len(values) == 1 else values

    raw["rt3_province"] = province
    raw["rt3_brand"] = "Rawson Properties"
    for key, dest in (("Status", "rt3_status"), ("Type", "rt3_type"), ("GPS", "rt3_gps_raw")):
        value = _clean(rec.get(key))
        if value:
            raw[dest] = value

    roster = _agents(rec)
    if roster:
        raw["rt3_agents"] = roster
        raw["rt3_co_agent_count"] = len(roster) - 1

    fittings = _kitchen_fittings(rec.get("Kitchens"))
    if fittings:
        raw["rt3_kitchen_fittings"] = fittings
    return raw


def _title(rec: BracketRecord, property_type: str | None, suburb: str | None) -> str | None:
    heading = _clean(rec.get("Heading"))
    if heading:
        return heading[:_TITLE_MAX].rstrip()
    if property_type and suburb:
        return f"{property_type} in {suburb}"
    return None


def to_import_record(rec: BracketRecord, *, province: str) -> tuple[dict[str, Any], list[str]]:
    """Return ``(record, image_urls)``. ``province`` is the config URL token, kept
    in ``raw_data.rt3_province`` for the per-province reconcile to scope on."""
    reference = (rec.get("Reference") or "").strip()
    type_raw = (rec.get("Type") or "").strip()
    price = (rec.get("Price") or "").strip()
    suburb = _clean(rec.get("Suburb"))
    property_type = _PROPERTY_TYPE.get(type_raw.lower(), type_raw or None)
    lat, lng = _split_gps(rec.get("GPS"))
    images = [u for u in rec.get_all("Image_URL") if u.strip()]
    title = _title(rec, property_type, suburb)
    roster = _agents(rec)
    primary = roster[0] if roster else {}

    record: dict[str, Any] = {
        "vendor_listing_id": reference,
        "title": title,
        "description": _clean(rec.get("Description")),
        "property_type": property_type,
        "listing_type": _s(rec, "Status"),
        "price": None if _is_poa(price) else price,
        "price_on_application": _is_poa(price),
        "bedrooms": _s(rec, "Beds"),
        "bathrooms": _s(rec, "Baths"),
        "garages": _s(rec, "Garages"),
        "parking_spaces": _s(rec, "Carports"),
        "floor_size": _s(rec, "Building_Size"),
        "erf_size": _s(rec, "Erf_Size"),
        "street_address": _clean(rec.get("Address")),
        "suburb": suburb,
        "latitude": lat,
        "longitude": lng,
        "agency_vendor_id": _s(rec, "Branch_ID"),
        "agency_name": _clean(rec.get("Branch_Name")),
        "agent_vendor_id": (primary.get("email") or primary.get("name") or "").strip().lower()
        or None,
        "agent_name": primary.get("name"),
        "features": _features(rec),
        "primary_image_url": images[0] if images else None,
        "listed_at": _s(rec, "Listed"),
    }
    record.update(_raw_data(rec, province))

    if not reference:
        record["__validation_error__"] = "Reference (vendor_listing_id) is missing"
    elif not title:
        record["__validation_error__"] = (
            f"no usable title for Reference {reference} "
            "(Heading empty and property_type+Suburb not both present)"
        )

    return record, images
