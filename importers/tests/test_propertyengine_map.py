"""Offline — the record mapper, the two vocabularies, the price + geography rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.propertyengine.decode import parse_feed
from iol_importers.propertyengine.map import _PROPERTY_TYPE, to_import_record
from iol_importers.propertyengine.validate import VALID_TYPES

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertyengine/fixtures"
XML_RECORDS = parse_feed((FIXTURES / "feed.xml").read_bytes())
BY_ID = {r["UniqueID"]: r for r in XML_RECORDS}


def _mapped(vid: str) -> dict:
    return to_import_record(BY_ID[vid])[0]


def test_every_appendix_b_type_has_an_explicit_mapping():
    # every documented Type (Appendix B) resolves to a target, none falls through
    unmapped = sorted(t for t in VALID_TYPES if t not in _PROPERTY_TYPE)
    assert unmapped == []


def test_status_maps_to_listing_type_vocabulary():
    assert _mapped("900001")["listing_type"] == "For Sale"
    assert _mapped("900003")["listing_type"] == "To Let"
    # Holiday -> To Let (listing_type enum has no Holiday); raw word kept
    holiday = _mapped("900004")
    assert holiday["listing_type"] == "To Let"
    assert holiday["propertyengine_status"] == "Holiday"


def test_price_zero_is_contact_for_price_not_missing():
    holiday = _mapped("900004")
    assert holiday["price"] is None
    assert holiday["price_on_application"] is True
    sale = _mapped("900001")
    assert sale["price"] == "2500000"
    assert sale["price_on_application"] is False


def test_bad_type_sets_validation_error():
    record = _mapped("900005")
    assert "__validation_error__" in record
    assert "Appendix B" in record["__validation_error__"]


def test_location_id_resolves_to_the_same_suburb_candidate_as_free_text():
    free_text = _mapped("900001")
    by_location = _mapped("900002")
    assert free_text["suburb"] == "Rondebosch"
    assert by_location["suburb"] == "Rondebosch"
    assert by_location["propertyengine_location_id"] == 3100047
    assert by_location["propertyengine_province"] == "Western Cape"


def test_coordinates_fall_back_to_appendix_a_centroid():
    # 900002 carries a Location but no Map*Coordinate of its own
    by_location = _mapped("900002")
    assert by_location["latitude"] == "-33.9635811"
    assert by_location["longitude"] == "18.4762764"
    # 900001 has its own coords — those win
    assert _mapped("900001")["latitude"] == "-33.963"


def test_office_maps_onto_agency():
    record = _mapped("900001")
    assert record["agency_vendor_id"] == "8001"
    assert record["agency_name"] == "Demo Realty Rondebosch"
    assert record["agent_vendor_id"] == "70001"
    assert record["agent_name"] == "Alex Carter"


@pytest.mark.parametrize("vid", sorted(BY_ID))
def test_every_fixture_record_maps_without_error(vid):
    record, urls = to_import_record(BY_ID[vid])
    assert record["vendor_listing_id"] == vid
    assert isinstance(urls, list)
