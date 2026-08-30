"""Map a raw PropCtrl ``Listing`` to the ``import_listings`` record contract.

Every mapping here is taken from the OpenAPI spec (``/v1-listing/swagger.json``)
and confirmed against real API responses. Fields whose meaning could not be
pinned down are listed in ``MAPPING_NOTES.md`` and left out rather than guessed;
some are copied verbatim into ``listings.raw_data`` via the non-promoted
``propctrl_*`` keys.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# propertyType enum -> canonical property_types.name (de-camel-cased). The
# name-ILIKE step in resolve_property_type does the final match, so these only
# need to be the human spelling of the enum.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")

# measurementUnit -> square-metre multiplier.
_SQM_PER_UNIT: dict[str, Decimal] = {
    "Metresquared": Decimal(1),
    "Hectare": Decimal(10_000),
    "Acre": Decimal("4046.8564224"),
}

_POA_OPTIONS = frozenset({"POA", "POAunderAuction"})

# Boolean amenity flags worth surfacing in listings.features (skips the flags that
# are not amenities: noTransferDuty, priceReduced, showLocation, standaloneBuilding).
_AMENITY_FLAGS: dict[str, str] = {
    "solarPanel": "Solar panels",
    "solarGeyser": "Solar geyser",
    "gasGeyser": "Gas geyser",
    "borehole": "Borehole",
    "waterTank": "Water tank",
    "backupBatteryInverter": "Backup battery / inverter",
    "backupWaterSupply": "Backup water supply",
    "generator": "Generator",
    "petsAllowed": "Pets allowed",
    "wheelchairAccessible": "Wheelchair accessible",
}

_FEATURE_COUNT_TYPES = {
    "bedrooms": "Bedroom",
    "bathrooms": "Bathroom",
    "garages": "Garage",
    "parking_spaces": "Parking",
}


def _s(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def de_camel(value: str) -> str:
    """``FlatApartment`` -> ``Flat Apartment``."""
    return _CAMEL_BOUNDARY.sub(" ", value)


def _area_sqm(area: object) -> str | None:
    if not isinstance(area, dict):
        return None
    size = area.get("size")
    if size in (None, ""):
        return None
    multiplier = _SQM_PER_UNIT.get(str(area.get("measurementUnit")))
    if multiplier is None:
        return None  # an unknown unit — flag, don't guess (see MAPPING_NOTES)
    return str((Decimal(str(size)) * multiplier).normalize())


def _feature_count(features: list[dict[str, Any]], feature_type: str) -> float | None:
    matching = [f for f in features if f.get("type") == feature_type]
    if not matching:
        return None
    # Each room is one entry, value is normally 1; a half-bath is 0.5; a parking
    # entry can carry a bay count. Summing the values covers all three.
    total = sum(float(f.get("value") or 0) for f in matching)
    return total if total else float(len(matching))


def _feature_list(raw: dict[str, Any], features: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for feat in features:
        for opt in feat.get("options") or []:
            label = _s(opt.get("description"))
            if label:
                out.append(label)
    for flag, label in _AMENITY_FLAGS.items():
        if raw.get(flag) is True:
            out.append(label)
    # de-duplicate, preserve first-seen order
    return list(dict.fromkeys(out))


def _street_address(raw: dict[str, Any], location: dict[str, Any]) -> str | None:
    parts = [_s(raw.get("doorNumber")), _s(raw.get("streetName"))]
    joined = " ".join(p for p in parts if p)
    return joined or _s(location.get("address"))


def _agent_name(agent: dict[str, Any]) -> str | None:
    parts = [_s(agent.get("firstName")), _s(agent.get("lastName"))]
    return " ".join(p for p in parts if p) or None


def to_import_record(
    raw: dict[str, Any],
    *,
    suburbs: dict[int, dict[str, Any]],
    agencies: dict[int, dict[str, Any]],
    branches: dict[int, dict[str, Any]],
    agents: dict[int, dict[str, Any]],
    change_type: str | None = None,
) -> dict[str, Any]:
    features = raw.get("features") or []
    location = raw.get("location") if isinstance(raw.get("location"), dict) else {}

    suburb_id = raw.get("suburbId")
    agency_id = raw.get("agencyId")
    branch_id = raw.get("branchId")
    agent_ids = raw.get("agentIds") or []
    agent_id = agent_ids[0] if agent_ids else None

    suburb = suburbs.get(suburb_id, {}) if suburb_id is not None else {}
    agency = agencies.get(agency_id, {}) if agency_id is not None else {}
    branch = branches.get(branch_id, {}) if branch_id is not None else {}
    agent = agents.get(agent_id, {}) if agent_id is not None else {}

    property_type_enum = _s(raw.get("propertyType"))

    record: dict[str, Any] = {
        "vendor_listing_id": str(raw["listingId"]),
        "vendor_listing_type": "listing",
        "listing_type": _s(raw.get("mandateType")),
        "property_type": de_camel(property_type_enum) if property_type_enum else None,
        "title": _s(raw.get("marketingHeading")),
        "description": _s(raw.get("marketingDescription")),
        "price": raw.get("listPrice"),
        "price_on_application": _s(raw.get("pricingOption")) in _POA_OPTIONS,
        "bedrooms": _feature_count(features, "Bedroom"),
        "bathrooms": _feature_count(features, "Bathroom"),
        "garages": _feature_count(features, "Garage"),
        "parking_spaces": _feature_count(features, "Parking"),
        "erf_size": _area_sqm(raw.get("erfSize")),
        "floor_size": _area_sqm(raw.get("floorArea")),
        "levies": raw.get("levy"),
        "rates_and_taxes": raw.get("rates"),
        "street_address": _street_address(raw, location),
        "complex_name": _s(raw.get("estateName")),
        "unit_number": _s(raw.get("doorNumber")),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "features": _feature_list(raw, features),
        "primary_image_url": _primary_image(raw),
        "suburb": _s(suburb.get("suburbName")),
        "agency_vendor_id": str(agency_id) if agency_id is not None else None,
        "agency_name": _s(agency.get("name")),
        "agent_vendor_id": str(agent_id) if agent_id is not None else None,
        "agent_name": _agent_name(agent),
        "listed_at": _s(raw.get("created")),
        "vendor_updated_at": _s(raw.get("updated")),
        # --- not promoted: copied verbatim into listings.raw_data -----------
        "propctrl_change_type": change_type,
        "propctrl_listing_number": _s(raw.get("listingNumber")),
        "propctrl_listing_status": _s(raw.get("listingStatus")),
        "propctrl_pricing_option": _s(raw.get("pricingOption")),
        "propctrl_ownership_type": _s(raw.get("ownershipType")),
        "propctrl_furnished_type": _s(raw.get("furnishedType")),
        "propctrl_lease_period": _s(raw.get("leasePeriod")),
        "propctrl_expires": _s(raw.get("expires")),
        "propctrl_branch_id": str(branch_id) if branch_id is not None else None,
        "propctrl_branch_name": _s(branch.get("name")),
        "propctrl_agent_ids": [str(a) for a in agent_ids],
        "propctrl_suburb_city": _s(suburb.get("city")),
        "propctrl_suburb_province": _s(suburb.get("province")),
        "propctrl_suburb_postal_code": _s(suburb.get("postalCode")),
        "propctrl_image_count": len(raw.get("images") or []),
    }
    if raw.get("commercialInfo"):
        record["propctrl_commercial_info"] = raw["commercialInfo"]
    if raw.get("farmInfo"):
        record["propctrl_farm_info"] = raw["farmInfo"]
    return record


def _primary_image(raw: dict[str, Any]) -> str | None:
    for image in raw.get("images") or []:
        url = _s(image.get("url"))
        if url:
            return url
    return None
