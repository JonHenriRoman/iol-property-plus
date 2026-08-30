"""Map a raw Propdata listing record to the ``import_listings`` record contract.

Only fields verified against real API responses are mapped. Everything uncertain
is listed in ``MAPPING_NOTES.md`` and left out (not guessed) — some of it is
copied verbatim into ``raw_data`` via the non-promoted ``propdata_*`` keys, which
the importer folds into ``listings.raw_data`` untouched.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .client import PropdataClient

RESIDENTIAL = "residential"
COMMERCIAL = "commercial"
HOLIDAY = "holiday"
PROJECTS = "projects"

# Category -> how listing_type is decided. residential/commercial read the record's
# own "For Sale" / "To Let" string; holiday is always a rental; a project is a
# development for sale.
_FORCED_LISTING_TYPE = {HOLIDAY: "Rental", PROJECTS: "Sale"}
_PROJECT_PROPERTY_TYPE = "Development"


def _s(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _join_address(raw: dict[str, Any]) -> str | None:
    parts = [_s(raw.get("street_number")), _s(raw.get("street_name"))]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _project_price(raw: dict[str, Any]) -> str | None:
    prices: list[Decimal] = []
    for plan in raw.get("property_types") or []:
        raw_price = plan.get("priced_from")
        if raw_price in (None, "", "0.00", "0"):
            continue
        try:
            prices.append(Decimal(str(raw_price)))
        except InvalidOperation:
            continue
    return str(min(prices)) if prices else None


def _agent_name(agent: dict[str, Any]) -> str | None:
    full = _s(agent.get("full_name"))
    if full:
        return full
    parts = [_s(agent.get("first_name")), _s(agent.get("last_name"))]
    return " ".join(p for p in parts if p) or None


def to_import_record(
    raw: dict[str, Any], *, category: str, client: PropdataClient
) -> dict[str, Any]:
    is_project = category == PROJECTS

    location = client.get_location(raw["location"]) if isinstance(raw.get("location"), int) else {}
    branch_id = raw.get("branch")
    agent_id = raw.get("agent")
    agent = client.get_agent(agent_id) if isinstance(agent_id, int) else {}
    branch = client.get_branch(branch_id) if isinstance(branch_id, int) else {}

    record: dict[str, Any] = {
        "vendor_listing_id": str(raw["id"]),
        "vendor_listing_type": category,
        "listing_type": _FORCED_LISTING_TYPE.get(category) or _s(raw.get("listing_type")),
        "property_type": _PROJECT_PROPERTY_TYPE if is_project else _s(raw.get("property_type")),
        "title": _s(raw.get("name")) if is_project else _s(raw.get("marketing_heading")),
        "description": _s(raw.get("description")),
        "price": _project_price(raw) if is_project else _s(raw.get("price")),
        "price_on_application": bool(raw.get("poa")),
        "bedrooms": None if is_project else _s(raw.get("bedrooms")),
        "bathrooms": None if is_project else _s(raw.get("bathrooms")),
        "garages": None if is_project else _s(raw.get("garages")),
        "parking_spaces": _s(raw.get("carports")),
        "floor_size": _s(raw.get("floor_size")),
        "erf_size": _s(raw.get("land_size")),
        "street_address": _join_address(raw),
        "complex_name": _s(raw.get("complex_name")) or _s(raw.get("building_name")),
        "unit_number": _s(raw.get("unit_number")),
        "suburb": _s(location.get("suburb")),
        "agency_vendor_id": str(branch_id) if branch_id else None,
        "agency_name": _s(branch.get("name")),
        "agent_vendor_id": str(agent_id) if agent_id else None,
        "agent_name": _agent_name(agent),
        "listed_at": _s(raw.get("on_market_since")) or _s(raw.get("created")),
        "vendor_updated_at": _s(raw.get("modified")),
        # --- not promoted: copied verbatim into listings.raw_data -----------
        "propdata_web_ref": _s(raw.get("web_ref")),
        "propdata_status": _s(raw.get("status")),
        "propdata_category": category,
        "propdata_image_ids": raw.get("listing_images") or [],
        "propdata_location_id": raw.get("location"),
        "propdata_postal_code": _s(location.get("postal_code")),
        "propdata_property24_id": location.get("property24_id"),
    }
    if is_project:
        record["propdata_plans"] = raw.get("property_types") or []
    return record
