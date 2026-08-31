"""Offline unit tests — Fusion <Listing> -> importer record."""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

import pytest

from fusion_mock import load
from iol_importers.fusion.areatree import AreaTree
from iol_importers.fusion.map import photo_urls, to_import_record


def _tree() -> AreaTree:
    tree = AreaTree()
    tree.apply_element(fromstring(load("snapshot_3")).find(".//AreaTree"))
    return tree


def _listings(name: str) -> dict:
    changes = fromstring(load(name))
    return {el.get("id"): el for el in changes.iter("Listing")}


TREE = _tree()
SNAP1 = _listings("snapshot_1")
SNAP2 = _listings("snapshot_2")


def _rec(el, *, areatree=TREE, **kw) -> dict:
    record, _ = to_import_record(el, areatree=areatree, **kw)
    return record


def test_house_core_fields():
    rec = _rec(SNAP1["100"], office_names={"4": "Demo Realty — Cape Town South"})
    assert rec["vendor_listing_id"] == "100"  # @id, not fusionRef
    assert rec["fusion_ref"] == "DR-100"
    assert rec["vendor_listing_type"] == "Residential"
    assert rec["listing_type"] == "Sale"
    assert rec["property_type"] == "House"
    assert rec["price"] == "2650000"
    assert rec["bedrooms"] == "4"
    assert rec["bathrooms"] == "2.5"
    assert rec["parking_spaces"] == 2
    assert rec["suburb"] == "Claremont"
    assert rec["street_address"] == "12 Grove Avenue"
    assert rec["agency_name"] == "Demo Realty — Cape Town South"
    assert rec["primary_image_url"] == "https://img.example.test/100/pic1.jpg"
    assert "Pool" in rec["features"]
    assert "Koi Pond" in rec["features"]
    assert "renovated family home" in rec["description"].lower()
    assert "<br" not in rec["description"]


def test_address_hidden_suppresses_street_but_keeps_suburb():
    rec = _rec(SNAP2["101"])
    assert rec["street_address"] is None
    assert rec["fusion_address_hidden"] is True
    assert rec["suburb"] == "Rondebosch"
    assert rec["listing_type"] == "Rent"
    assert rec["property_type"] == "Apartment"  # "Flat" -> Apartment
    assert rec["price"] == "14500"
    assert rec["fusion_price_suffix"] == "PerMonth"


def test_hectare_land_area_converted_and_unresolved_suburb():
    rec = _rec(SNAP2["102"])
    assert rec["erf_size"] == "14000"  # 1.4 ha
    assert rec["property_type"] == "Vacant Land"  # "Land" -> Vacant Land
    assert rec["suburb"] is None  # suburbId 99 not in the crosswalk
    assert rec["fusion_suburb_id"] == "99"
    assert rec["latitude"] is None  # "0" dropped


def test_photo_urls_ordered_and_deduped():
    assert photo_urls(SNAP1["100"]) == [
        "https://img.example.test/100/pic1.jpg",
        "https://img.example.test/100/pic2.jpg",
    ]


def test_title_falls_back_when_no_marketing_header():
    el = fromstring(
        '<Listing id="9"><Type listingType="Sale" listingZone="Residential" '
        'propertyType="House" /><Address suburbId="8" /></Listing>'
    )
    assert _rec(el)["title"] == "House for sale in Claremont"


@pytest.mark.parametrize("name", ["snapshot_1", "snapshot_2", "delta_1"])
def test_every_fixture_listing_maps(name):
    for el in _listings(name).values():
        record, urls = to_import_record(el, areatree=TREE)
        assert record["vendor_listing_id"]
        assert record["title"]
        assert isinstance(urls, list)
