"""Offline — the JSON/XML front end and the two fixtures agreeing."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.propertyengine.decode import (
    FeedDecodeError,
    as_list,
    get,
    parse_feed,
    sniff_format,
)
from iol_importers.propertyengine.map import to_import_record

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertyengine/fixtures"
JSON_BODY = (FIXTURES / "feed.json").read_bytes()
XML_BODY = (FIXTURES / "feed.xml").read_bytes()

# The importer-facing keys — the raw propertyengine_* passthrough deliberately
# differs between the two fixtures (the XML one carries extra real-world fields).
_CORE_KEYS = (
    "vendor_listing_id",
    "listing_type",
    "property_type",
    "title",
    "description",
    "price",
    "price_on_application",
    "bedrooms",
    "bathrooms",
    "garages",
    "erf_size",
    "floor_size",
    "levies",
    "rates_and_taxes",
    "latitude",
    "longitude",
    "features",
    "suburb",
    "agency_vendor_id",
    "agency_name",
    "agent_vendor_id",
    "agent_name",
    "listed_at",
    "vendor_updated_at",
    "primary_image_url",
    "__validation_error__",
)


def test_sniff_format_from_first_byte():
    assert sniff_format(b'  \n {"Listings": {}}') == "json"
    assert sniff_format(b"\xef\xbb\xbf<listings/>") == "xml"
    assert sniff_format(b"", "application/json") == "json"
    with pytest.raises(FeedDecodeError):
        sniff_format(b"neither")


def test_both_fixtures_yield_five_property_records():
    assert len(parse_feed(JSON_BODY, "application/json")) == 5
    assert len(parse_feed(XML_BODY, "application/xml")) == 5


def test_json_and_xml_map_to_the_same_core_record():
    json_recs = {r["vendor_listing_id"]: r for r, _ in map(to_import_record, parse_feed(JSON_BODY))}
    xml_recs = {r["vendor_listing_id"]: r for r, _ in map(to_import_record, parse_feed(XML_BODY))}
    assert json_recs.keys() == xml_recs.keys()
    for vid in json_recs:
        j = {k: json_recs[vid].get(k) for k in _CORE_KEYS}
        x = {k: xml_recs[vid].get(k) for k in _CORE_KEYS}
        assert j == x, vid


def test_single_and_multiple_images_both_normalise():
    records = parse_feed(XML_BODY)
    by_id = {get(r, "UniqueID"): r for r in records}
    one, _ = to_import_record(by_id["900002"])
    many, many_urls = to_import_record(by_id["900001"])
    assert one["propertyengine_photo_count"] == 1
    assert many["propertyengine_photo_count"] == 2
    assert len(many_urls) == 2


def test_absent_bedrooms_stays_none_for_studio():
    records = parse_feed(XML_BODY)
    studio = next(r for r in records if get(r, "UniqueID") == "900003")
    record, _ = to_import_record(studio)
    assert record["bedrooms"] is None
    assert record["property_type"] == "Apartment"


def test_as_list_normalises():
    assert as_list(None) == []
    assert as_list({"a": 1}) == [{"a": 1}]
    assert as_list([1, 2]) == [1, 2]
