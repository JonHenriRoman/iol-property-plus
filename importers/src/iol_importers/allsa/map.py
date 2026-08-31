"""Map an AllSA :class:`~iol_importers.allsa.parse.Property` to the Step 14
``import_listings`` contract. Pure — no I/O, no DB.

Traps this codifies (all confirmed against the real feed):

* ``Title`` is **tenure** (``Freehold`` / ``Sectional Title``), *not* the headline.
  ``Heading`` is the headline. ``Title`` goes to ``raw_data.allsa_tenure`` and
  never near ``record["title"]``.
* ``Status`` real values are ``For Sale`` and ``To Rent`` (the brief said
  "To Let"); all are accepted and normalised by the importer.
* ``Price`` ``0.00`` means price-on-application, not a free listing.
* ``Type`` is free text — the explicit dict covers the 12 observed values and
  anything else falls through to ``resolve_property_type``'s name match + per-feed
  mapping table (a genuinely unknown type becomes a counted ``mapping`` error,
  never a silent default).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .features import parse_features
from .parse import Property

# AllSA free-text `Type` -> our curated property_types.name (listings/_scratch.py
# seed). Unmapped values are passed through untouched for resolve_property_type.
_PROPERTY_TYPE: dict[str, str] = {
    "house": "House",
    "apartment": "Apartment",
    "townhouse": "Townhouse",
    "office": "Office",
    "vacant land": "Vacant Land",
    "farm": "Farm",
    # No hospitality/retail taxonomy — fold into the commercial/industrial rows.
    "retail": "Commercial",
    "business": "Commercial",
    "accommodation": "Commercial",
    "warehouse": "Industrial",
    "factory": "Industrial",
    "storage": "Industrial",
}


def _f(prop: Property, key: str) -> str:
    return prop.fields.get(key, "").strip()


def _is_poa(price: str) -> bool:
    try:
        return Decimal(price) == 0
    except InvalidOperation:
        return False


def to_import_record(prop: Property) -> tuple[dict[str, Any], list[str]]:
    """Return ``(record, photo_urls)``."""
    reference = _f(prop, "Reference")
    heading = _f(prop, "Heading")
    price = _f(prop, "Price")
    type_raw = _f(prop, "Type")
    parsed = parse_features(prop.features)

    record: dict[str, Any] = {
        "vendor_listing_id": reference,
        "title": heading or None,
        "description": _f(prop, "Description") or None,
        "property_type": _PROPERTY_TYPE.get(type_raw.lower(), type_raw or None),
        "listing_type": _f(prop, "Status") or None,
        "price": None if _is_poa(price) else (price or None),
        "price_on_application": _is_poa(price),
        "suburb": _f(prop, "Suburb") or None,
        "agency_vendor_id": _f(prop, "BranchId") or None,
        "agency_name": _f(prop, "Agency") or None,
        "agent_vendor_id": (_f(prop, "Agent_Email") or "").lower() or None,
        "agent_name": _f(prop, "Agent_Name") or None,
        "features": parsed.labels,
        "primary_image_url": prop.images[0] if prop.images else None,
    }
    record.update(parsed.columns)

    raw: dict[str, Any] = {
        "allsa_agency_id": _f(prop, "AgencyId") or None,
        "allsa_branch_id": _f(prop, "BranchId") or None,
        "allsa_agency_location": _f(prop, "Agency_Location") or None,
        "allsa_agency_website": _f(prop, "Agency_Website") or None,
        "allsa_agent_title": _f(prop, "Agent_Title") or None,
        "allsa_agent_cell": _f(prop, "Agent_Cell") or None,
        "allsa_agent_tel": _f(prop, "Agent_Tel") or None,
        "allsa_agent_email": _f(prop, "Agent_Email") or None,
        "allsa_url": _f(prop, "Url") or None,
        "allsa_tenure": _f(prop, "Title") or None,
        "allsa_rental_period": _f(prop, "Rental_Period") or None,
        "allsa_type": type_raw or None,
        "allsa_status": _f(prop, "Status") or None,
        "allsa_city_town": _f(prop, "CityTown") or None,
        "allsa_province": _f(prop, "Province") or None,
        "allsa_image_urls": list(prop.images),
        "allsa_features_extra": parsed.extra or None,
    }
    raw.update(parsed.raw_dates)
    record.update({k: v for k, v in raw.items() if v not in (None, [], {})})

    if not reference:
        record["__validation_error__"] = "Reference (vendor_listing_id) is missing"
    elif not heading:
        record["__validation_error__"] = f"Heading (title) is missing for Reference {reference}"

    return record, list(prop.images)
