"""Map a decoded PropertyEngine ``Property`` to the Step 14 ``import_listings`` contract.

Pure — no I/O, no DB. Input is one nested dict from :mod:`.decode` (JSON object or
flattened XML element, same shape either way). Output is a plain dict carrying only
:data:`iol_importers.listings.importer.PROMOTED_KEYS` plus ``propertyengine_*``
raw keys, and — when :func:`iol_importers.propertyengine.validate.validate_record`
rejected it — ``__validation_error__`` so the importer records it.

Two controlled vocabularies are mapped through explicit dicts here:

* ``Status`` -> the doc's listing-type words (``listings.listing_type`` is the
  ``Sale|Rental|Unknown`` enum with **no Holiday** — a holiday let is still a
  rental; the raw value is kept in ``raw_data``).
* ``Type`` -> ``property_types.name``. Every one of the 41 Appendix B values maps
  explicitly; a value outside the list is a validation failure (handled in
  ``validate``), never a silent default.

The doc's ``Price == 0`` means "Contact for Price" — ``price=None`` +
``price_on_application=True`` — and a *missing* ``Price`` tag is not ``0``.
``Bedrooms`` is *removed* for a studio, so its absence maps to ``None``, never ``0``.
"""

from __future__ import annotations

import re
from typing import Any

from .decode import as_list, get
from .locations import Location, lookup

# Status (doc + real lowercase `status`) -> the importer's listing-type vocabulary.
# Holiday -> To Let: listing_type has no Holiday value and a short-term holiday
# rental is still a rental. The original word survives as propertyengine_status.
_LISTING_TYPE: dict[str, str] = {
    "for sale": "For Sale",
    "to let": "To Let",
    "holiday": "To Let",
}

# Appendix B `Type` -> our property_types.name. Targets are the curated set the
# other adapters were built against (listings/_scratch.py seed): House, Apartment,
# Townhouse, Vacant Land, Cluster, Farm, Apartment Block, Office, Commercial,
# Industrial, Flat Apartment, Residential Estate, Development, Workshop.
# Judgement calls (documented in MAPPING_NOTES.md):
#   - Flat -> our distinct "Flat Apartment" row, not collapsed into Apartment.
#   - Hospitality (Bed & Breakfast, Guest House(s), Hotel, Hotel Room) -> Commercial:
#     we have no hospitality taxonomy.
#   - Legal/structural descriptors (Freehold, Freestanding, Bungalow, Villa) -> House.
#   - Gated Estate -> Residential Estate.
#   - Mini Factory / Minifactory are two real rows in the doc's own tables
#     (a spelling variant, not our typo) and map identically.
_PROPERTY_TYPE: dict[str, str] = {
    # Basic types
    "apartment": "Apartment",
    "cluster": "Cluster",
    "farm": "Farm",
    "flat": "Flat Apartment",
    "house": "House",
    "office": "Office",
    "small holding": "Farm",
    "townhouse": "Townhouse",
    "vacant land": "Vacant Land",
    # Speciality types
    "apartment block": "Apartment Block",
    "bed & breakfast": "Commercial",
    "building": "Commercial",
    "bungalow": "House",
    "business": "Commercial",
    "duplex": "Apartment",
    "equestrian property": "Farm",
    "factory": "Industrial",
    "freehold": "House",
    "freestanding": "House",
    "garden cottage": "House",
    "gated estate": "Residential Estate",
    "guest house": "Commercial",
    "guesthouse": "Commercial",
    "hotel": "Commercial",
    "hotel room": "Commercial",
    "industrial yard": "Industrial",
    "investment": "Commercial",
    "mini factory": "Industrial",
    "minifactory": "Industrial",
    "penthouse": "Apartment",
    "place of worship": "Commercial",
    "retail": "Commercial",
    "room": "Apartment",
    "sectional title": "Apartment",
    "serviced office": "Office",
    "showroom": "Commercial",
    "simplex": "Apartment",
    "storage unit": "Industrial",
    "studio apartment": "Apartment",
    "villa": "House",
    "warehouse": "Industrial",
}

_WS_RE = re.compile(r"\s+")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse(value: Any) -> str | None:
    text = _text(value)
    return _WS_RE.sub(" ", text).strip() if text is not None else None


def _number(value: Any) -> str | None:
    """Keep a numeric value as text for the importer's own ``to_decimal`` / ``to_int``
    (which tolerate junk and route it to ``error_type='parse'``). Blank -> None."""
    return _text(value)


def _price_fields(value: Any) -> tuple[str | None, bool]:
    """``Price``: ``0`` (doc: "Contact for Price") or a missing tag -> (None, True/None).

    Returns ``(price, price_on_application)``. A genuine ``0`` sets
    ``price_on_application`` True with ``price`` None; a missing tag leaves both
    unset (price None, PoA False); a real amount passes through as text.
    """
    text = _text(value)
    if text is None:
        return None, False
    try:
        amount = float(text.replace(",", ""))
    except ValueError:
        # let the importer's to_decimal reject it as a parse error
        return text, False
    if amount == 0:
        return None, True
    return text, False


def _listing_type(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return _LISTING_TYPE.get(text.lower(), text)


def _property_type(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return _PROPERTY_TYPE.get(text.lower(), text)


def _first_agent(record: dict[str, Any]) -> dict[str, Any]:
    for wrap in as_list(get(record, "Agents")):
        agent = get(wrap, "Agent", "agent")
        if isinstance(agent, dict):
            return agent
        if isinstance(wrap, dict) and get(wrap, "AgentID", "AgentId") is not None:
            return wrap
    return {}


def photo_urls(record: dict[str, Any]) -> list[str]:
    """Ordered, de-duplicated ``Images.Image[].ImageURL`` list."""
    images = get(record, "Images")
    out: list[str] = []
    for image in as_list(get(images, "Image")):
        url = _text(get(image, "ImageURL")) if isinstance(image, dict) else _text(image)
        if url:
            out.append(url)
    return list(dict.fromkeys(out))


def _geography(record: dict[str, Any]) -> tuple[dict[str, Any], Location | None]:
    """Resolve the geography half of the record.

    When ``Location`` (Appendix A gazetteer id) is present, its locality name is the
    suburb candidate and its province/area/centroid go into ``raw_data``. When it is
    absent, the free-text ``Suburb`` / ``City``|``CityTown`` / ``Province`` are used
    directly.
    """
    location = lookup(get(record, "Location"))
    fields: dict[str, Any] = {}
    if location is not None:
        fields["suburb"] = location.locality
        fields["propertyengine_location_id"] = location.location_id
        fields["propertyengine_province"] = location.province
        if location.area:
            fields["propertyengine_location_area"] = location.area
        fields["propertyengine_location_locality"] = location.locality
        return fields, location

    raw_location = _text(get(record, "Location"))
    if raw_location is not None:
        # a Location id we could not resolve — warn (adapter), keep it verbatim,
        # fall through to any free-text the record also carries
        fields["propertyengine_location_unresolved"] = raw_location

    fields["suburb"] = _text(get(record, "Suburb"))
    fields["propertyengine_city"] = _text(get(record, "City", "CityTown"))
    fields["propertyengine_province"] = _text(get(record, "Province"))
    return fields, None


def _features(record: dict[str, Any]) -> list[str]:
    parking = _collapse(get(record, "Parking"))
    return [parking] if parking else []


def to_import_record(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return ``(import record, ordered photo source URLs)`` for one ``Property``."""
    from .validate import validate_record

    agent = _first_agent(record)
    office = get(record, "Office") or {}
    geo_fields, location = _geography(record)

    price, poa = _price_fields(get(record, "Price"))

    # `MapYCoordinate` is latitude (negative in SA); `MapXCoordinate` is longitude.
    # Fall back to the Appendix A centroid only when the record has no coords.
    latitude = _number(get(record, "MapYCoordinate"))
    longitude = _number(get(record, "MapXCoordinate"))
    if latitude is None and longitude is None and location is not None:
        latitude = str(location.latitude)
        longitude = str(location.longitude)

    out: dict[str, Any] = {
        "vendor_listing_id": _text(get(record, "UniqueID")),
        "listing_type": _listing_type(get(record, "Status", "status")),
        "property_type": _property_type(get(record, "Type")),
        "title": _collapse(get(record, "Heading")),
        "description": _collapse(get(record, "Description")),
        "price": price,
        "price_on_application": poa,
        "bedrooms": _number(get(record, "Bedrooms")),
        "bathrooms": _number(get(record, "Bathrooms")),
        "garages": _number(get(record, "Garages")),
        "erf_size": _number(get(record, "ErfSize")),
        "floor_size": _number(get(record, "PropertySize")),
        "levies": _number(get(record, "Levy")),
        "rates_and_taxes": _number(get(record, "Rates")),
        "latitude": latitude,
        "longitude": longitude,
        "features": _features(record),
        "agency_vendor_id": _text(get(office, "ID")),
        "agency_name": _text(get(office, "Name")),
        "agent_vendor_id": _text(get(agent, "AgentID", "AgentId")),
        "agent_name": _text(get(agent, "AgentName")),
        "listed_at": _text(get(record, "CreatedOn")),
        "vendor_updated_at": _text(get(record, "UpdatedOn")),
        "primary_image_url": None,
        # --- not promoted: kept verbatim in listings.raw_data ------------------
        "propertyengine_reference": _text(get(record, "Reference")),
        "propertyengine_status": _text(get(record, "Status", "status")),
        "propertyengine_type": _text(get(record, "Type")),
        "propertyengine_mapped_category": _text(get(record, "ListingType")),
        "propertyengine_price_prefix": _text(get(record, "PricePrefix")),
        "propertyengine_available_from": _text(get(record, "AvailableFrom")),
        "propertyengine_agent_phone": _text(get(agent, "AgentPhone")),
        "propertyengine_agent_mobile": _text(get(agent, "AgentMobile")),
        "propertyengine_agent_email": _text(get(agent, "AgentEmail")),
        "propertyengine_agent_photo": _text(get(agent, "AgentPhoto")),
        "propertyengine_office_email": _text(get(office, "Email", "email")),
        "propertyengine_office_phone": _text(get(office, "TelephoneNumber")),
        "propertyengine_office_address": _text(get(office, "PhysicalAddress")),
        "propertyengine_office_province": _text(get(office, "Province")),
        "propertyengine_photo_count": len(photo_urls(record)),
    }
    out.update(geo_fields)

    urls = photo_urls(record)
    if urls:
        out["primary_image_url"] = urls[0]

    reason = validate_record(record)
    if reason is not None:
        out["__validation_error__"] = f"PropertyEngine listing rejected: {reason}"

    return out, urls
