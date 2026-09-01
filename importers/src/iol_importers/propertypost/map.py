"""Map one PropertyPost :class:`~iol_importers.bracket_kv.BracketRecord` to the
Step 14 ``import_listings`` contract. Pure — no I/O, no DB.

PropertyPost specifics codified here:

* **``Beds``/``Baths`` and ``Bedrooms``/``Bathrooms`` are the same fact under two
  names.** :func:`_coalesce_pair` takes ``Bedrooms``/``Bathrooms`` (the more
  complete side in the live feed) and falls back to ``Beds``/``Baths`` when a side
  is blank. A genuine numeric disagreement (never seen live) is not silently
  dropped — it is recorded in ``raw_data.propertypost_<field>_conflict`` and
  flagged to the caller via ``__field_conflicts__``.
* ``Heading`` is empty on a few records; :func:`_title` synthesises one from the
  first line of ``Description``, then from ``"{property_type} in {suburb}"``.
* ``GPS`` is simply **absent** from a record with no coordinates — there is no
  sentinel value to special-case, unlike MyRoof's bare comma.
* All amenity keys (``Fence``, ``Alarm``, ``Garden`` … ``Kitchens``) are pure
  ``YES`` booleans here — ``Kitchens: YES`` is a feature flag, not MyRoof's count
  and not RT3's embedded list.
* ``Type`` is a small clean vocabulary; every live value maps. An unmapped value
  still passes through raw so ``resolve_property_type`` quarantines it rather than
  guessing.
* ``Description`` carries no ``<p>`` tags (unlike MyRoof) — it is only stripped.
* ``Admin_ID`` is a constant company contact, distinct from the per-listing
  ``Agent_Name``/``Email`` — it is kept as ``raw_data.propertypost_admin_email``
  and never used as the agent identity.
* ``Features_Description`` is free-text prose with an unstructured
  ``Label - Value - Detail`` triple format — kept verbatim in ``raw_data``, never
  parsed.

Every key that is not promoted to a column is captured under
``propertypost_<Key>`` in ``raw_data`` (a list when the key repeats).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from iol_importers.bracket_kv import BracketRecord

# PropertyPost `Type` -> seeded property_types.name (listings/_scratch.py). Every
# live value maps; an unmapped value is passed through for resolve_property_type
# to reject rather than guessed.
_PROPERTY_TYPE: dict[str, str] = {
    "house": "House",
    "commercial": "Commercial",
    "townhouse": "Townhouse",
    "apartment or flat": "Apartment",
    "flat": "Apartment",
    "stand": "Vacant Land",
    "smallholding": "Farm",
}

# Amenity keys that are pure "YES" booleans in this feed -> a human feature label.
_FLAG_FEATURES: tuple[tuple[str, str], ...] = (
    ("Fence", "Fence"),
    ("Alarm", "Alarm"),
    ("Garden", "Garden"),
    ("Pool", "Pool"),
    ("Security", "Security"),
    ("Patio", "Patio"),
    ("Balcony", "Balcony"),
    ("Views", "Views"),
    ("Staff_Accomm", "Staff Accommodation"),
    ("Laundry", "Laundry"),
    ("Study", "Study"),
    ("Family_Rooms", "Family Room"),
    ("Reception_Rooms", "Reception Room"),
    ("Kitchens", "Kitchen"),
)
_TRUE = frozenset({"yes", "y", "true", "1"})

# Keys consumed by typed columns / features / explicit raw_data aliases —
# everything else falls to raw_data under its own name.
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
        "Bedrooms",
        "Bathrooms",
        "Garages",
        "Carports",
        "Building_Size",
        "Erf_Size",
        "Address",
        "Suburb",
        "GPS",
        "Branch_ID",
        "Branch_Name",
        "Email",
        "Agent_Name",
        "Admin_ID",
        "Area",
        "Province",
        "Image_URL",
        "Listed",
        "Verified",
        *(key for key, _ in _FLAG_FEATURES),
    }
)

_TITLE_MAX = 120


def _clean(raw: str | None) -> str | None:
    return raw.strip() if raw and raw.strip() else None


def _s(rec: BracketRecord, key: str) -> str | None:
    return (rec.get(key) or "").strip() or None


def _num_or_none(raw: str | None) -> str | None:
    """Keep a numeric string, but drop a literal ``0`` — PropertyPost sends
    ``Erf_Size: 0`` / ``Building_Size: 0`` for "unknown", not a real 0 m²."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        if Decimal(text) == 0:
            return None
    except InvalidOperation:
        return text
    return text


def _is_poa(price: str) -> bool:
    if not price:
        return True
    try:
        return Decimal(price) == 0
    except InvalidOperation:
        return False


def _coalesce_pair(
    rec: BracketRecord, primary: str, secondary: str
) -> tuple[str | None, str | None]:
    """Return ``(value, conflict)``. ``value`` prefers ``primary`` (the more
    complete side live) and falls back to ``secondary`` when ``primary`` is blank.
    ``conflict`` is a human string only when both sides are non-blank AND parse to
    different numbers — which the live feed never shows but must not pass
    silently."""
    a = (rec.get(primary) or "").strip()
    b = (rec.get(secondary) or "").strip()
    conflict = None
    if a and b:
        try:
            if Decimal(a) != Decimal(b):
                conflict = f"{primary}={a} {secondary}={b}"
        except InvalidOperation:
            if a != b:
                conflict = f"{primary}={a!r} {secondary}={b!r}"
    return (a or b or None, conflict)


def _title(rec: BracketRecord, property_type: str | None, suburb: str | None) -> str | None:
    heading = _clean(rec.get("Heading"))
    if heading:
        return heading
    description = _clean(rec.get("Description"))
    if description:
        first_line = description.splitlines()[0].strip()
        if first_line:
            return first_line[:_TITLE_MAX].rstrip()
    bits = [b for b in (property_type, "in", suburb) if b]
    return " ".join(bits) if suburb and property_type else None


def _split_gps(raw: str | None) -> tuple[str | None, str | None]:
    """``GPS`` is one ``"lat,lng"`` string; the "no coordinates" case is the key
    being absent entirely (``raw`` is ``None``) — nothing to special-case."""
    if not raw:
        return (None, None)
    parts = raw.split(",")
    if len(parts) < 2:
        return (None, None)
    lat, lng = parts[0].strip(), parts[1].strip()
    return (lat or None, lng or None)


def _features(rec: BracketRecord) -> list[str]:
    return [label for key, label in _FLAG_FEATURES if (rec.get(key) or "").strip().lower() in _TRUE]


def _raw_data(rec: BracketRecord) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key, all_values in rec.as_dict().items():
        if key in _PROMOTED_KEYS:
            continue
        values = [v for v in all_values if v and v.strip()]
        if not values:
            continue
        raw[f"propertypost_{key}"] = values[0] if len(values) == 1 else values

    aliases = (
        ("Status", "propertypost_status"),
        ("Type", "propertypost_type"),
        ("Admin_ID", "propertypost_admin_email"),  # company contact, NOT the agent
        ("Area", "propertypost_city"),
        ("Province", "propertypost_province"),
    )
    for key, dest in aliases:
        value = _clean(rec.get(key))
        if value:
            raw[dest] = value
    return raw


def _apply_coalesced_pairs(record: dict[str, Any], rec: BracketRecord) -> None:
    """Fill ``bedrooms`` / ``bathrooms`` from the duplicate name pairs, recording a
    conflict in ``raw_data`` and ``__field_conflicts__`` if the two sides disagree."""
    conflicts: list[str] = []
    for field_name, primary, secondary in (
        ("bedrooms", "Bedrooms", "Beds"),
        ("bathrooms", "Bathrooms", "Baths"),
    ):
        value, conflict = _coalesce_pair(rec, primary, secondary)
        record[field_name] = value
        if conflict:
            conflicts.append(field_name)
            record[f"propertypost_{field_name}_conflict"] = conflict
    if conflicts:
        record["__field_conflicts__"] = conflicts


def to_import_record(rec: BracketRecord) -> tuple[dict[str, Any], list[str]]:
    """Return ``(record, image_urls)``.

    The record carries two private keys the adapter consumes and strips before the
    importer sees typed columns: ``__validation_error__`` (a counted reject) and
    ``__field_conflicts__`` (a list of field names whose duplicate pair disagreed).
    """
    reference = (rec.get("Reference") or "").strip()
    type_raw = (rec.get("Type") or "").strip()
    price = (rec.get("Price") or "").strip()
    suburb = _clean(rec.get("Suburb"))
    property_type = _PROPERTY_TYPE.get(type_raw.lower(), type_raw or None)
    lat, lng = _split_gps(rec.get("GPS"))
    images = [u for u in rec.get_all("Image_URL") if u.strip()]
    title = _title(rec, property_type, suburb)

    record: dict[str, Any] = {
        "vendor_listing_id": reference,
        "title": title,
        "description": _clean(rec.get("Description")),
        "property_type": property_type,
        "listing_type": _s(rec, "Status"),
        "price": None if _is_poa(price) else price,
        "price_on_application": _is_poa(price),
        "garages": _s(rec, "Garages"),
        "parking_spaces": _s(rec, "Carports"),
        "floor_size": _num_or_none(rec.get("Building_Size")),
        "erf_size": _num_or_none(rec.get("Erf_Size")),
        "street_address": _clean(rec.get("Address")),
        "suburb": suburb,
        "latitude": lat,
        "longitude": lng,
        "agency_vendor_id": _s(rec, "Branch_ID"),
        "agency_name": _clean(rec.get("Branch_Name")),
        "agent_vendor_id": (rec.get("Email") or "").strip().lower() or None,
        "agent_name": _clean(rec.get("Agent_Name")),
        "features": _features(rec),
        "primary_image_url": images[0] if images else None,
        "listed_at": _s(rec, "Listed"),
        "vendor_updated_at": _s(rec, "Verified"),
    }
    _apply_coalesced_pairs(record, rec)
    record.update(_raw_data(rec))

    if not reference:
        record["__validation_error__"] = "Reference (vendor_listing_id) is missing"
    elif not title:
        record["__validation_error__"] = (
            f"no usable title for Reference {reference} "
            "(Heading, Description and property_type+Suburb all empty)"
        )

    return record, images
