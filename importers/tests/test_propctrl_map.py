"""Offline tests for the PropCtrl -> importer-record mapping."""

from __future__ import annotations

import collections
import json
from decimal import Decimal

import pytest

from iol_importers.propctrl.map import de_camel, to_import_record
from propctrl_mock import FIXTURES, load_listings

_SUBURBS = {s["suburbId"]: s for s in json.loads((FIXTURES / "suburbs.json").read_text())}
_AGENCIES = {a["agencyId"]: a for a in json.loads((FIXTURES / "agencies.json").read_text())}
_BRANCHES = {b["branchId"]: b for b in json.loads((FIXTURES / "branches.json").read_text())}
_AGENTS = {a["agentId"]: a for a in json.loads((FIXTURES / "agents.json").read_text())}


def _map(raw: dict, **kw) -> dict:
    return to_import_record(
        raw, suburbs=_SUBURBS, agencies=_AGENCIES, branches=_BRANCHES, agents=_AGENTS, **kw
    )


def _by_id(listing_id: int) -> dict:
    return next(x for x in load_listings() if x["listingId"] == listing_id)


def test_de_camel():
    assert de_camel("FlatApartment") == "Flat Apartment"
    assert de_camel("VacantLand") == "Vacant Land"
    assert de_camel("House") == "House"


def test_core_fields_and_listing_type():
    raw = _by_id(7247652)  # House, Sale
    rec = _map(raw, change_type="New")
    assert rec["vendor_listing_id"] == "7247652"
    assert rec["vendor_listing_type"] == "listing"
    assert rec["listing_type"] == "Sale"
    assert rec["property_type"] == "House"
    assert rec["title"] == raw["marketingHeading"]
    assert rec["price"] == raw["listPrice"]
    assert rec["propctrl_change_type"] == "New"


def test_flat_apartment_is_de_camel_cased():
    rec = _map(_by_id(7507782))
    assert rec["property_type"] == "Flat Apartment"


def test_rental_mandate_maps_to_rental():
    rec = _map(_by_id(7243837))
    assert rec["listing_type"] == "Rental"


def test_room_counts_come_from_features():
    raw = _by_id(7247652)
    counts = collections.Counter(f["type"] for f in raw["features"])
    rec = _map(raw)
    assert rec["bedrooms"] == counts["Bedroom"]
    assert rec["bathrooms"] == counts["Bathroom"]


def test_vacant_land_has_no_room_counts():
    rec = _map(_by_id(7590466))  # VacantLand
    assert rec["bedrooms"] is None
    assert rec["bathrooms"] is None


def test_hectare_erf_size_is_converted_to_sqm():
    raw = _by_id(7500959)  # Farm, erfSize in Hectare
    assert raw["erfSize"]["measurementUnit"] == "Hectare"
    rec = _map(raw)
    assert Decimal(rec["erf_size"]) == Decimal(str(raw["erfSize"]["size"])) * 10_000


def test_poa_pricing_sets_price_on_application():
    raw = dict(_by_id(7247652))
    raw["pricingOption"] = "POA"
    assert _map(raw)["price_on_application"] is True


def test_coordinates_and_primary_image_are_carried():
    raw = _by_id(7247652)
    rec = _map(raw)
    assert rec["latitude"] == raw["location"]["latitude"]
    assert rec["longitude"] == raw["location"]["longitude"]
    assert rec["primary_image_url"] == raw["images"][0]["url"]


def test_internal_remarks_are_never_carried():
    raw = dict(_by_id(7247652))
    raw["internalRemarks"] = "private: seller divorcing, will drop 200k"
    rec = _map(raw)
    assert "internalRemarks" not in rec
    assert not any("divorcing" in str(v) for v in rec.values())


def test_suburb_and_agency_resolve_via_lookups():
    raw = _by_id(7247652)
    rec = _map(raw)
    assert rec["suburb"] == _SUBURBS[raw["suburbId"]]["suburbName"]
    assert rec["agency_name"] == _AGENCIES[raw["agencyId"]]["name"]
    assert rec["agent_vendor_id"] == str(raw["agentIds"][0])


@pytest.mark.parametrize("listing_id", [x["listingId"] for x in load_listings()])
def test_every_fixture_listing_maps_without_error(listing_id):
    rec = _map(_by_id(listing_id))
    assert rec["vendor_listing_id"]
    assert rec["title"]
