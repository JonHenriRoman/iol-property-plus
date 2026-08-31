"""Map a Fusion ``<Listing>`` element to the ``import_listings`` record contract.

Controlled vocabularies (``listingType`` / ``listingZone`` / ``propertyType``) are
mapped through explicit dicts; ``listingZone`` also namespaces
``resolve_property_type`` so the same word (``Office``, ``Land``) resolves per
zone. The suburb name comes from the AreaTree crosswalk (``Address/@suburbId`` ->
name -> ``resolve_suburb``); ``raw_data.fusion_suburb_id`` is always kept so a
later AreaTree batch can backfill an unresolved ``suburb_id``.

Photos are **hotlinked** (operator's choice) — ``primary_image_url`` is the first
``<Photo url>`` and every ``<Photo url>`` becomes a ``listing_media`` row; nothing
is downloaded. The doc's "must download to local repository" wording is recorded
as a deviation in ``MAPPING_NOTES.md``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree.ElementTree import Element

# Type/@propertyType (lowercased) -> canonical property_types.name. Unknown values
# pass through for resolve_property_type's name-ILIKE / per-feed mapping step.
_PROPERTY_TYPE: dict[str, str] = {
    "apartment": "Apartment",
    "flat": "Apartment",
    "bachelor flat": "Apartment",
    "penthouse": "Apartment",
    "loft": "Apartment",
    "studio": "Apartment",
    "sectional title": "Apartment",
    "house": "House",
    "duet": "House",
    "duplex": "House",
    "simplex": "House",
    "villa": "House",
    "garden cottage": "House",
    "room": "House",
    "townhouse": "Townhouse",
    "cluster": "Cluster",
    "estate": "Residential Estate",
    "gated village": "Residential Estate",
    "golf estate": "Residential Estate",
    "wildlife estate": "Residential Estate",
    "land": "Vacant Land",
    "agricultural holding": "Farm",
    "game farm": "Farm",
    "lifestyle farm": "Farm",
    "smallholding": "Farm",
    "commercial farm": "Farm",
    "guest farm": "Farm",
    "business": "Commercial",
    "commercial property": "Commercial",
    "commercial & industrial": "Commercial",
    "bed & breakfast": "Commercial",
    "hotel": "Commercial",
    "game lodge": "Commercial",
    "hunting lodge": "Commercial",
    "leisure & hotels": "Commercial",
    "tourism": "Commercial",
    "lodge": "Commercial",
    "retail": "Commercial",
    "retail & offices": "Commercial",
    "shareblock": "Commercial",
    "other commercial": "Commercial",
    "office": "Office",
    "factory": "Industrial",
    "warehouse": "Industrial",
    "industrial": "Industrial",
}

_LISTING_TYPE: dict[str, str] = {"Sale": "Sale", "Rent": "Rent"}

_POA_SUFFIXES = frozenset({"POA", "SBT"})

_AREA_TO_SQM: dict[str, Decimal] = {
    "sqm": Decimal(1),
    "ha": Decimal(10_000),
    "ac": Decimal("4046.8564224"),
}

# SecondaryFeatures boolean-ish attrs -> a features[] label. Count attrs
# (numEnsuites, numStoreys, …) are kept in raw_data instead.
_FEATURE_FLAGS: dict[str, str] = {
    "hasStudy": "Study",
    "hasBalcony": "Balcony",
    "hasPatio": "Patio",
    "hasPool": "Pool",
    "hasDeck": "Deck",
    "hasSpaBath": "Spa Bath",
    "hasGym": "Gym",
    "hasGolfCourse": "Golf Course",
    "hasClubHouse": "Club House",
    "hasSquashCourt": "Squash Court",
    "hasTennisCourt": "Tennis Court",
    "hasStaffQuarters": "Staff Quarters",
    "hasLaundry": "Laundry",
    "hasStorage": "Storage",
    "hasWalkInCloset": "Walk-in Closet",
    "hasBuildInCupboards": "Built-in Cupboards",
    "isFurnished": "Furnished",
    "isWheelChairFriendly": "Wheelchair Friendly",
    "hasAircon": "Air Conditioning",
    "hasTV": "TV",
    "hasSatellite": "Satellite",
    "arePetsAllowed": "Pets Allowed",
    "hasFence": "Fence",
    "hasSecurityPost": "Security Post",
    "hasAccessGate": "Access Gate",
    "hasAlarm": "Alarm System",
    "hasScenicView": "Scenic View",
    "hasSeaView": "Sea View",
    "hasKitchen": "Kitchen",
    "hasLapa": "Lapa",
    "hasElectricFencing": "Electric Fencing",
    "hasBuiltInBraai": "Built-in Braai",
    "hasFireplace": "Fireplace",
    "hasGardenCottage": "Garden Cottage",
    "hasJettyBerth": "Jetty / Berth",
    "hasScullery": "Scullery",
    "hasPantry": "Pantry",
    "hasGuestToilet": "Guest Toilet",
    "hasEntranceHall": "Entrance Hall",
    "hasBorehole": "Borehole",
    "hasIrrigationSystem": "Irrigation System",
    "hasPaving": "Paving",
    "hasGarden": "Garden",
    "hasIntercom": "Intercom",
    "hasFamilyTvRoom": "Family TV Room",
    "hasCentralHeating": "Central Heating",
    "hasReception": "Reception",
    "hasConferenceRoom": "Conference Room",
    "hasBoardRoom": "Boardroom",
    "hasShowRoom": "Showroom",
    "hasPassengerLift": "Passenger Lift",
    "hasFreightLift": "Freight Lift",
    "hasFireSuppression": "Fire Suppression",
    "hasFireEscape": "Fire Escape",
    "hasLoadingBay": "Loading Bay",
    "hasBasement": "Basement",
    "has24HourSecurity": "24 Hour Security",
    "hasCCTV": "CCTV",
    "hasCafeteria": "Cafeteria",
    "hasStaffLounge": "Staff Lounge",
    "hasBackupGenerator": "Backup Generator",
    "hasWaterTanks": "Water Tanks",
    "hasSolarPanels": "Solar Panels",
    "hasSolarGeyser": "Solar Geyser",
    "hasGasStove": "Gas Stove",
    "hasGasGeyser": "Gas Geyser",
    "hasFibre": "Fibre",
    "hasPrePaidElectricity": "Prepaid Electricity",
    "hasPrePaidWater": "Prepaid Water",
    "hasBoundaryWall": "Boundary Wall",
    "hasWallSpikes": "Wall Spikes",
    "hasBoomGate": "Boom Gate",
    "hasPerimeterBeams": "Perimeter Beams",
    "hasBackupBattery": "Backup Battery",
    "hasWellpoint": "Wellpoint",
    "hasInverter": "Inverter",
    "hasFeedInInverter": "Feed-in Inverter",
    "SmokingAllowed": "Smoking Allowed",
}

_SECONDARY_COUNT_ATTRS = (
    "numEnsuites",
    "numLounges",
    "numDiningAreas",
    "numFlatlets",
    "numStoreys",
    "numPeopleSleeps",
)

_TRUE = frozenset({"true", "1", "yes", "y"})


def _a(element: Element | None, attr: str) -> str | None:
    if element is None:
        return None
    value = (element.get(attr) or "").strip()
    return value or None


def _num(value: object) -> object:
    if value in (None, "", "0", "0.0", 0):
        return None
    return value


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def _area_sqm(value: str | None, units: str | None) -> object:
    value = _num(value)
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    number *= _AREA_TO_SQM.get((units or "sqm").strip().lower(), Decimal(1))
    return f"{number.normalize():f}"


def _property_type(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    return _PROPERTY_TYPE.get(raw_value.strip().lower(), raw_value.strip())


def _description(listing: Element) -> str | None:
    node = listing.find("Description")
    if node is None:
        return None
    parts: list[str] = [node.text or ""]
    for child in node:
        parts.append("\n" if child.tag == "br" else "")
        parts.append(child.tail or "")
    text = re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()
    return text or None


def _street_address(address: Element | None) -> str | None:
    if address is None or _flag(address.get("addressHidden")):
        return None
    parts = [_a(address, "streetNumber"), _a(address, "streetName"), _a(address, "streetType")]
    return " ".join(p for p in parts if p) or None


def _coord(address: Element | None, attr: str) -> object:
    value = _a(address, attr)
    if value is None:
        return None
    try:
        if Decimal(value) == 0:
            return None
    except InvalidOperation:
        return None
    return value


def _features(listing: Element) -> list[str]:
    out: list[str] = []
    secondary = listing.find("SecondaryFeatures")
    if secondary is not None:
        out.extend(label for attr, label in _FEATURE_FLAGS.items() if _flag(secondary.get(attr)))
    for custom in listing.findall("CustomFeatures/CustomFeature"):
        name = _a(custom, "name")
        if name:
            out.append(name)
    return list(dict.fromkeys(out))


def photo_urls(listing: Element) -> list[str]:
    urls: list[str] = []
    for photo in listing.findall("Photos/Photo"):
        url = _a(photo, "url")
        if url:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _price(listing: Element) -> tuple[object, bool]:
    sale = listing.find("SaleDetails")
    rent = listing.find("RentDetails")
    if sale is not None:
        return _num(sale.get("sellingPrice")), (sale.get("priceSuffix") or "") in _POA_SUFFIXES
    if rent is not None:
        return _num(rent.get("rentalPrice")), (rent.get("priceSuffix") or "") in _POA_SUFFIXES
    return None, False


def _agent_ref_ids(listing: Element) -> list[str]:
    return [i for i in (_a(ref, "id") for ref in listing.findall("Agents/AgentRef")) if i]


def to_import_record(
    listing: Element,
    *,
    areatree: Any,
    event_timestamp: str | None = None,
    office_names: dict[str, str] | None = None,
    agent_names: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    office_names = office_names or {}
    agent_names = agent_names or {}

    type_el = listing.find("Type")
    zone = _a(type_el, "listingZone")
    address = listing.find("Address")
    main = listing.find("MainFeatures")
    sale = listing.find("SaleDetails")
    rent = listing.find("RentDetails")
    secondary = listing.find("SecondaryFeatures")

    suburb_id = _a(address, "suburbId")
    suburb_name = areatree.suburb_name(suburb_id) if suburb_id else None
    price, poa = _price(listing)

    office_id = _a(listing, "officeId")
    agency_name = office_names.get(office_id or "") or " — ".join(
        p for p in (_a(listing, "agencyName"), _a(listing, "branchName")) if p
    )
    agent_ids = _agent_ref_ids(listing)
    agent_id = agent_ids[0] if agent_ids else None
    agent_name = agent_names.get(agent_id or "") if agent_id else None

    covered = int(_num(_a(main, "numCoveredParkings")) or 0) if main is not None else 0
    open_bays = int(_num(_a(main, "numOpenParkings")) or 0) if main is not None else 0

    header_node = listing.find("Marketing/MarketingHeader")
    title = (header_node.text or "").strip() if header_node is not None else None
    if not title:
        listing_type = _a(type_el, "listingType")
        prop = _property_type(_a(type_el, "propertyType")) or "Property"
        bits = [prop, "for", listing_type.lower()] if listing_type else [prop]
        if suburb_name:
            bits += ["in", suburb_name]
        title = " ".join(bits)

    record: dict[str, Any] = {
        "vendor_listing_id": _a(listing, "id"),
        "vendor_listing_type": zone,
        "listing_type": _LISTING_TYPE.get(
            _a(type_el, "listingType") or "", _a(type_el, "listingType")
        ),
        "property_type": _property_type(_a(type_el, "propertyType")),
        "title": title or None,
        "description": _description(listing),
        "price": price,
        "price_on_application": poa,
        "bedrooms": _num(_a(main, "numBedrooms")),
        "bathrooms": _num(_a(main, "numBathrooms")),
        "garages": _num(_a(main, "numGarages")),
        "parking_spaces": (covered + open_bays) or None,
        "erf_size": _area_sqm(_a(main, "landArea"), _a(main, "landAreaUnits")),
        "floor_size": _area_sqm(_a(main, "floorArea"), _a(main, "floorAreaUnits")),
        "levies": _num(_a(sale, "levy")),
        "rates_and_taxes": _num(_a(sale, "rates")),
        "street_address": _street_address(address),
        "latitude": _coord(address, "latitude"),
        "longitude": _coord(address, "longitude"),
        "suburb": suburb_name,
        "features": _features(listing),
        "primary_image_url": (photo_urls(listing) or [None])[0],
        "agency_vendor_id": office_id,
        "agency_name": agency_name or None,
        "agent_vendor_id": agent_id,
        "agent_name": agent_name,
        "listed_at": _a(listing, "publishedDateTime"),
        "vendor_updated_at": event_timestamp,
        # --- not promoted: kept verbatim in listings.raw_data --------------
        "fusion_ref": _a(listing, "fusionRef"),
        "fusion_agency_ref": _a(listing, "agencyRef"),
        "fusion_suburb_id": suburb_id,
        "fusion_development_id": _a(listing, "developmentId"),
        "fusion_imported_from": _a(listing, "importedFrom"),
        "fusion_featured": _flag(listing.get("featured")),
        "fusion_sale_state": _a(sale, "saleState"),
        "fusion_rental_state": _a(rent, "rentalState"),
        "fusion_mandate_type": _a(sale, "mandateType"),
        "fusion_mandate_expiry": _a(sale, "mandateExpiry"),
        "fusion_price_suffix": _a(sale, "priceSuffix") or _a(rent, "priceSuffix"),
        "fusion_deposit": _num(_a(rent, "deposit")),
        "fusion_virtual_tour_url": _a(listing, "virtualTourUrl"),
        "fusion_youtube_video_id": _a(listing, "youTubeVideoId"),
        "fusion_address_hidden": _flag(address.get("addressHidden"))
        if address is not None
        else False,
        "fusion_agent_ref_ids": agent_ids,
        "fusion_photo_urls": photo_urls(listing),
        "fusion_document_urls": [
            u for u in (_a(d, "url") for d in listing.findall("Documents/Document")) if u
        ],
    }

    if secondary is not None:
        for attr in _SECONDARY_COUNT_ATTRS:
            value = _num(secondary.get(attr))
            if value is not None:
                record[f"fusion_{attr}"] = value
    for optional_tag in ("CommercialListingDetails", "HolidayRentalDetails", "CommercialFeatures"):
        node = listing.find(optional_tag)
        if node is not None and node.attrib:
            record[f"fusion_{optional_tag}"] = dict(node.attrib)

    return record, photo_urls(listing)
