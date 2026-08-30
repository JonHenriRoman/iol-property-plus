"""Offline tests for the RE/MAX -> importer-record mapping."""

from __future__ import annotations

import json

import pytest

from iol_importers.remax.map import to_import_record
from remax_mock import FIXTURES, load_inner

_LISTINGS = json.loads((FIXTURES / "listings.json").read_text())


def _prop(listing_id: str) -> dict:
    return json.loads(_LISTINGS[listing_id]["data"])["property"][0]


def _map(listing_id: str) -> dict:
    return to_import_record(_prop(listing_id))


def test_house_core_fields():
    rec = _map("1601348")
    assert rec["vendor_listing_id"] == "1601348"
    assert rec["vendor_listing_type"] == "listing"
    assert rec["listing_type"] == "For Sale"
    assert rec["property_type"] == "Vacant Land"  # "Vacant Land / Plot: residential"
    assert rec["remax_property_type_subtype"] == "residential"
    assert rec["price"] == 295000
    assert rec["agency_vendor_id"] == "128"
    assert rec["agent_vendor_id"] == "891173"


def test_rental_mandate_and_periodicity():
    rec = _map("4295569")
    assert rec["listing_type"] == "To Rent"
    assert rec["property_type"] == "Townhouse"
    assert rec["remax_price_periodicity"] == "Per Month"
    assert rec["street_address"] == "27 Knoppiesdoring"


def test_commercial_base_segment_and_subtype():
    rec = _map("36612803")
    assert rec["property_type"] == "Commercial"
    assert "Guesthouse" in rec["remax_property_type_subtype"]
    assert rec["bedrooms"] == 20 and rec["bathrooms"] == 22


def test_geo_location_empty_is_dropped():
    rec = _map("1601348")
    assert rec["latitude"] is None and rec["longitude"] is None


def test_feature_flags_and_custom_features_become_the_array():
    prop = _prop("1601348")
    prop["features"]["pool"] = "true"
    prop["features"]["custom_features"] = "Koi Pond, Solar Geyser"
    rec = to_import_record(prop)
    assert "Pool" in rec["features"]
    assert "Electric Fencing" in rec["features"]  # was already true in the fixture
    assert "Koi Pond" in rec["features"] and "Solar Geyser" in rec["features"]


def test_description_html_is_stripped():
    prop = _prop("1601348")
    prop["description"] = {"_cdata": "<p>Big <b>house</b>.<br/>Nice view.</p>"}
    rec = to_import_record(prop)
    assert "<" not in rec["description"]
    assert "Big house. Nice view." in rec["description"]


def test_null_and_undefined_headings_are_dropped():
    prop = _prop("1601348")
    prop["heading"] = {"_cdata": "null For Sale in Nowhere"}
    prop["marketing_header"] = "Real Title"
    assert (
        to_import_record(prop)["title"] == "null For Sale in Nowhere"
    )  # kept: only bare "null" is dropped
    prop["heading"] = {"_cdata": "null"}
    assert to_import_record(prop)["title"] == "Real Title"


@pytest.mark.parametrize("listing_id", list(_LISTINGS))
def test_every_fixture_listing_maps(listing_id):
    rec = _map(listing_id)
    assert rec["vendor_listing_id"]
    assert rec["title"]
    assert rec["property_type"] in {
        "House",
        "Apartment",
        "Townhouse",
        "Vacant Land",
        "Farm",
        "Commercial",
        "Industrial",
    }


def test_agents_page_property_uses_folded_agent_and_branch():
    inner = load_inner("agents_page.json")
    prop = inner["properties"]["property"][0]
    prop["_remax_agent"] = inner["agent_details"]
    prop["_remax_branch"] = inner["branches"]["branch_details"][0]
    rec = to_import_record(prop)
    assert rec["agent_vendor_id"] == str(inner["agent_details"]["agent_id"])
    assert rec["agency_vendor_id"] == str(inner["branches"]["branch_details"][0]["branch_id"])
