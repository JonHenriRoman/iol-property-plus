"""Map an Entegral ``officelistings`` listing to the ``import_listings`` contract.

The field structure follows the Sync API ``CreateOrUpdateListing`` object
(``https://api.entegral.net/SyncAPI.json``): flat keys, ``"1"``/``"0"`` string
booleans, ``"-"`` / ``""`` sentinels, ``latlng`` as one ``"lat,lng"`` string,
``contact[]`` carrying the agent, and the office name coming from the
``officeslist`` entry (``contact`` has only the office *id*).

Controlled vocabularies (``propertyType``, ``propertyStatus``) are mapped through
explicit dicts. Every listing must carry an agent name and an office name — a
listing missing either gets ``__validation_error__`` set so the importer records
it (never a silent import). Exact source keys are pinned by a sandbox probe;
anything uncertain is kept in ``raw_data`` under ``entegral_*``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_SENTINELS = {"", "-", "null", "none", "undefined", "n/a", "na"}
_TRUE = {"1", "true", "yes", "y"}

# propertyType (doc enum, lowercased) -> canonical property_types.name. Unknown
# values pass through for resolve_property_type's name-ILIKE / mapping-table step.
_PROPERTY_TYPE: dict[str, str] = {
    "apartment": "Apartment",
    "flat": "Apartment",
    "penthouse": "Apartment",
    "cluster": "Cluster",
    "house": "House",
    "cottage": "House",
    "duet": "House",
    "holiday accommodation": "House",
    "retirement village": "House",
    "townhouse": "Townhouse",
    "vacant land": "Vacant Land",
    "vacant land / plot": "Vacant Land",
    "vacant land residential": "Vacant Land",
    "vacant land commercial": "Vacant Land",
    "vacant land agricultural": "Vacant Land",
    "commercial": "Commercial",
    "business": "Commercial",
    "lodge": "Commercial",
    "guest house": "Commercial",
    "office": "Commercial",
    "restaurant": "Commercial",
    "hotel": "Commercial",
    "retail": "Commercial",
    "shop": "Commercial",
    "mixed use": "Commercial",
    "industrial": "Industrial",
    "industrial land": "Industrial",
    "farm": "Farm",
    "game farm": "Farm",
    "small holding": "Farm",
    "smallholding": "Farm",
}

# propertyStatus (doc enum, lowercased) -> the doc's listing-type vocabulary.
_LISTING_TYPE: dict[str, str] = {
    "for sale": "For Sale",
    "pending sale": "For Sale",
    "auction": "For Sale",
    "sold": "For Sale",
    "rental daily": "To Rent",
    "rental weekly": "To Rent",
    "rental monthly": "To Rent",
    "rental yearly": "To Rent",
    "to let": "To Rent",
    "to rent": "To Rent",
    "rental": "To Rent",
}

# "1"/"0" string-boolean flags -> a features[] label when set.
_BOOL_FLAGS: dict[str, str] = {
    "pool": "Pool",
    "petsAllowed": "Pets Allowed",
    "flatLet": "Flatlet",
    "furnished": "Furnished",
    "isReduced": "Price Reduced",
}

# freetext "…Features" description fields -> split into features[] (drop sentinels).
_FEATURE_TEXT_KEYS = (
    "propertyFeatures",
    "securityFeatures",
    "gardenFeatures",
    "kitchenFeatures",
    "bedroomFeatures",
    "bathroomFeatures",
)
_FEATURE_ARRAY_KEYS = ("electricalSupply", "waterSupply")

_RAW_INT_KEYS = ("study", "livingAreas", "staffAccommodation")


def _s(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _SENTINELS else text or None


def _num(value: object) -> object:
    if value in (None, "", "0", 0, "-"):
        return None
    return value


def _flag(value: object) -> bool:
    return str(value).strip().lower() in _TRUE


def _ts(value: object) -> str | None:
    """``2015/06/17 10:34:35`` / ``2015/07/06 20:14`` -> ISO ``2015-06-17 10:34:35``."""
    text = _s(value)
    if text is None:
        return None
    return text.replace("/", "-")


def _latlng(value: object) -> tuple[str | None, str | None]:
    text = _s(value)
    if text is None or "," not in text:
        return None, None
    lat_raw, _, lng_raw = text.partition(",")
    return _coord(lat_raw), _coord(lng_raw)


def _coord(raw: str) -> str | None:
    raw = raw.strip()
    try:
        if Decimal(raw) == 0:
            return None
    except InvalidOperation:
        return None
    return raw


def _area_sqm(size: object, unit: object) -> object:
    value = _num(size)
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if str(unit).strip().lower() in {"ha", "hectare", "hectares"}:
        number *= Decimal(10_000)
    return f"{number.normalize():f}"


def _property_type(raw_value: object) -> str | None:
    text = _s(raw_value)
    if text is None:
        return None
    return _PROPERTY_TYPE.get(text.lower(), text)


def _listing_type(raw_value: object) -> object:
    text = _s(raw_value)
    if text is None:
        return None
    return _LISTING_TYPE.get(text.lower(), text)


def _feature_list(listing: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key, label in _BOOL_FLAGS.items():
        if _flag(listing.get(key)):
            out.append(label)
    for key in _FEATURE_TEXT_KEYS:
        text = _s(listing.get(key))
        if text:
            out.extend(p.strip() for p in re.split(r"[,;|]", text) if p.strip())
    for key in _FEATURE_ARRAY_KEYS:
        value = listing.get(key)
        if isinstance(value, list):
            out.extend(str(v).strip() for v in value if str(v).strip())
    return list(dict.fromkeys(out))


def _clean_description(value: object) -> str | None:
    text = _s(value)
    if text is None:
        return None
    without_tags = re.sub(r"<[^>]+>", " ", text)
    collapsed = re.sub(r"\s+", " ", without_tags)
    return re.sub(r"\s+([.,;:!?)])", r"\1", collapsed).strip() or None


def _first_contact(listing: dict[str, Any]) -> dict[str, Any]:
    contacts = listing.get("contact")
    if isinstance(contacts, list):
        for entry in contacts:
            if isinstance(entry, dict):
                return entry
    if isinstance(contacts, dict):
        return contacts
    return {}


def photo_urls(listing: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for photo in listing.get("photos") or []:
        url = _s(photo.get("imgUrl") or photo.get("url")) if isinstance(photo, dict) else _s(photo)
        if url:
            out.append(url)
    return list(dict.fromkeys(out))


def _title(listing: dict[str, Any], property_type: str | None) -> str | None:
    explicit = _s(listing.get("title"))
    if explicit:
        return explicit
    bits = [property_type, "in", _s(listing.get("suburb"))]
    joined = " ".join(b for b in bits if b)
    return joined or None


def to_import_record(
    listing: dict[str, Any],
    *,
    office: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(import record, ordered photo source URLs)``."""
    office = office or {}
    contact = _first_contact(listing)

    from .client import office_name, office_reference

    office_ref = office_reference(office) or _s(contact.get("clientOfficeID"))
    office_display = office_name(office)
    agent_name = _s(contact.get("fullName")) or _s(contact.get("name"))
    agent_vendor_id = _s(contact.get("clientAgentID"))

    property_type = _property_type(listing.get("propertyType"))
    lat, lng = _latlng(listing.get("latlng"))
    carports = _num(listing.get("carports")) or 0
    open_parking = _num(listing.get("openparking")) or 0
    parking = (int(carports) if str(carports).isdigit() else 0) + (
        int(open_parking) if str(open_parking).isdigit() else 0
    )

    record: dict[str, Any] = {
        "vendor_listing_id": _s(listing.get("clientPropertyID")),
        "vendor_listing_type": "officelistings",
        "listing_type": _listing_type(listing.get("propertyStatus")),
        "property_type": property_type,
        "title": _title(listing, property_type),
        "description": _clean_description(listing.get("description")),
        "price": _num(listing.get("price")),
        "price_on_application": False,
        "bedrooms": _num(listing.get("beds")),
        "bathrooms": _num(listing.get("baths")),
        "garages": _num(listing.get("garages")),
        "parking_spaces": parking or None,
        "erf_size": _area_sqm(listing.get("landSize"), listing.get("landSizeType")),
        "floor_size": _area_sqm(listing.get("buildingSize"), listing.get("buildingSizeType")),
        "levies": _num(listing.get("levy")),
        "rates_and_taxes": _num(listing.get("ratesAndTaxes")),
        "street_address": _street_address(listing),
        "complex_name": _s(listing.get("complexName")),
        "unit_number": _s(listing.get("unitNumber")),
        "latitude": lat,
        "longitude": lng,
        "suburb": _s(listing.get("suburb")),
        "features": _feature_list(listing),
        "agency_vendor_id": office_ref,
        "agency_name": office_display,
        "agent_vendor_id": agent_vendor_id,
        "agent_name": agent_name,
        "listed_at": _ts(listing.get("listDate")),
        "vendor_updated_at": _ts(listing.get("timestamp") or listing.get("listDate")),
        # --- not promoted: kept verbatim in listings.raw_data ---------------
        "entegral_office_reference": office_ref,
        "entegral_property_status": _s(listing.get("propertyStatus")),
        "entegral_property_type_raw": _s(listing.get("propertyType")),
        "entegral_mandate": _s(listing.get("mandate")),
        "entegral_currency": _s(listing.get("currency")),
        "entegral_price_unit": _s(listing.get("priceUnit")),
        "entegral_town": _s(listing.get("town")),
        "entegral_province": _s(listing.get("province")),
        "entegral_expiry_date": _ts(listing.get("expiryDate")),
        "entegral_is_development": _flag(listing.get("isDevelopment")),
        "entegral_vt_url": _s(listing.get("vtUrl")),
        "entegral_agent_cell": _s(contact.get("cell")),
        "entegral_agent_email": _s(contact.get("email")),
        "entegral_agent_profile": _s(contact.get("profile")),
        "entegral_agent_logo": _s(contact.get("logo")),
        "entegral_office_logo": _s(office.get("logo")),
        "entegral_photo_count": len(photo_urls(listing)),
    }
    for key in _RAW_INT_KEYS:
        value = _num(listing.get(key))
        if value is not None:
            record[f"entegral_{key.lower()}"] = value

    files = listing.get("files")
    if isinstance(files, list) and files:
        record["entegral_files"] = files

    missing = [
        label
        for label, value in (("agent name", agent_name), ("office name", office_display))
        if not value
    ]
    if missing:
        record["__validation_error__"] = (
            "Entegral listing is missing " + " and ".join(missing) + " — every "
            "listing must display the agent's name and their office's name"
        )

    return record, photo_urls(listing)


def _street_address(listing: dict[str, Any]) -> str | None:
    parts = [_s(listing.get("streetNumber")), _s(listing.get("streetName"))]
    return " ".join(p for p in parts if p) or None
