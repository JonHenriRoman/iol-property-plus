"""AllSA Property -> import_listings record mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.allsa.map import to_import_record
from iol_importers.allsa.parse import parse_feed

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/allsa/fixtures"


def _props():
    return {
        p.fields["Reference"]: p
        for p in parse_feed(FIXTURES.joinpath("feed.xml").read_bytes()).properties
    }


def test_reference_is_vendor_listing_id_and_heading_is_title():
    rec, _ = to_import_record(_props()["1604015"])
    assert rec["vendor_listing_id"] == "1604015"
    assert rec["title"] == "Office space for sale in Brandwag"


def test_title_tag_is_tenure_not_the_headline():
    rec, _ = to_import_record(_props()["1604015"])
    assert rec["allsa_tenure"] == "Freehold"
    assert "Freehold" not in (rec["title"] or "")


def test_to_rent_status_maps_to_rental():
    rec, _ = to_import_record(_props()["3001"])
    assert rec["listing_type"] == "To Rent"  # importer normalises to the Rental enum
    assert rec["allsa_rental_period"] == "Per Month"


def test_price_zero_is_price_on_application():
    rec, _ = to_import_record(_props()["5003"])
    assert rec["price"] is None
    assert rec["price_on_application"] is True


def test_unknown_type_passes_through_untouched():
    rec, _ = to_import_record(_props()["7005"])
    assert rec["property_type"] == "Townhouse"
    rec2, _ = to_import_record(_props()["8006"])
    assert rec2["property_type"] == "Commercial"  # Retail -> Commercial


def test_missing_heading_sets_validation_error():
    rec, _ = to_import_record(_props()["9007"])
    assert "__validation_error__" in rec


def test_photos_hotlinked_in_order():
    rec, photos = to_import_record(_props()["1604015"])
    assert photos[0] == "https://img.example.test/90000/1604015-a.jpg"
    assert rec["primary_image_url"] == photos[0]
    assert rec["allsa_image_urls"] == photos


def test_branch_id_is_the_agency_vendor_id():
    rec, _ = to_import_record(_props()["5003"])
    assert rec["agency_vendor_id"] == "90250"
    assert rec["agent_vendor_id"] == "cory@example.test"


@pytest.mark.parametrize(
    "type_raw,expected",
    [
        ("House", "House"),
        ("Apartment", "Apartment"),
        ("Office", "Office"),
        ("Vacant Land", "Vacant Land"),
        ("Townhouse", "Townhouse"),
        ("Retail", "Commercial"),
        ("Warehouse", "Industrial"),
        ("Farm", "Farm"),
        ("Accommodation", "Commercial"),
        ("Business", "Commercial"),
        ("Factory", "Industrial"),
        ("Storage", "Industrial"),
    ],
)
def test_every_observed_type_value(type_raw, expected):
    from iol_importers.allsa.parse import Property

    prop = Property(
        fields={"Reference": "x", "Heading": "h", "Type": type_raw, "Status": "For Sale"},
        images=(),
        features=(),
    )
    rec, _ = to_import_record(prop)
    assert rec["property_type"] == expected
