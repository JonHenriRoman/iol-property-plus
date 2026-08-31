"""Offline unit tests — Entegral listing -> importer record mapping."""

from __future__ import annotations

import copy

import pytest

from entegral_mock import office_listings, offices
from iol_importers.entegral.map import photo_urls, to_import_record

OFFICE = offices()[0]  # OFF001
OFF001 = {o["officereference"]: o for o in offices()}["OFF001"]
LISTINGS = {x["clientPropertyID"]: x for x in office_listings("OFF001")}
LISTINGS_2 = {x["clientPropertyID"]: x for x in office_listings("OFF002")}


def _rec(listing: dict, office: dict = OFF001) -> dict:
    record, _ = to_import_record(listing, office=office)
    return record


def test_house_core_fields():
    rec = _rec(LISTINGS["L-1001"])
    assert rec["vendor_listing_id"] == "L-1001"
    assert rec["vendor_listing_type"] == "officelistings"
    assert rec["listing_type"] == "For Sale"
    assert rec["property_type"] == "House"
    assert rec["price"] == 2650000
    assert rec["bedrooms"] == 4
    assert rec["bathrooms"] == 2.5
    assert rec["garages"] == 2
    assert rec["parking_spaces"] == 2  # 0 carports + 2 open
    assert rec["suburb"] == "Claremont"
    assert rec["latitude"] == "-33.9820"
    assert rec["longitude"] == "18.4650"
    assert "__validation_error__" not in rec


def test_rental_maps_to_to_rent():
    rec = _rec(LISTINGS["L-1002"])
    assert rec["listing_type"] == "To Rent"
    assert rec["property_type"] == "Apartment"  # "Flat" -> Apartment
    assert rec["entegral_price_unit"] == "monthly"
    assert rec["price"] == 14500


def test_zero_and_blank_latlng_dropped():
    assert _rec(LISTINGS["L-1002"])["latitude"] is None  # "0,0"
    assert _rec(LISTINGS_2["L-2002"])["latitude"] is None  # ""


def test_hectare_land_size_converted_to_sqm():
    rec = _rec(LISTINGS_2["L-2002"], office=offices()[1])
    assert rec["erf_size"] == "14000"  # 1.4 ha
    assert rec["property_type"] == "Vacant Land"


def test_features_from_flags_and_freetext_and_arrays():
    feats = _rec(LISTINGS["L-1001"])["features"]
    assert "Pool" in feats
    assert "Pets Allowed" in feats
    assert "Solar Panels" in feats  # electricalSupply array
    assert "Alarm" in feats  # securityFeatures freetext, comma-split
    assert "Municipal Water" in feats
    # de-duplicated, order preserved
    assert len(feats) == len(set(feats))


def test_html_stripped_from_description():
    desc = _rec(LISTINGS["L-1001"])["description"]
    assert "<b>" not in desc
    assert "beautifully renovated" in desc
    assert "  " not in desc


def test_agent_and_office_name_promoted():
    rec = _rec(LISTINGS["L-1001"])
    assert rec["agent_name"] == "Jordan Adams"
    assert rec["agent_vendor_id"] == "AG-501"
    assert rec["agency_name"] == "Demo Property Group Claremont"
    assert rec["agency_vendor_id"] == "OFF001"
    assert rec["entegral_agent_email"] == "jordan@example.test"


def test_missing_agent_name_sets_validation_error():
    listing = copy.deepcopy(LISTINGS["L-1001"])
    listing["contact"][0]["fullName"] = ""
    rec = _rec(listing)
    assert "agent name" in rec["__validation_error__"]


def test_missing_office_name_sets_validation_error():
    rec = _rec(LISTINGS["L-1001"], office={"officereference": "OFF001"})
    assert "office name" in rec["__validation_error__"]


def test_photo_urls_ordered():
    urls = photo_urls(LISTINGS["L-1001"])
    assert urls == [
        "https://img.entegral.net/p/OFF001/L-1001_1.jpg",
        "https://img.entegral.net/p/OFF001/L-1001_2.png",
    ]


@pytest.mark.parametrize("ref", ["OFF001", "OFF002"])
def test_every_fixture_listing_maps(ref):
    office = {o["officereference"]: o for o in offices()}[ref]
    for listing in office_listings(ref):
        record, urls = to_import_record(listing, office=office)
        assert record["vendor_listing_id"]
        assert isinstance(urls, list)
