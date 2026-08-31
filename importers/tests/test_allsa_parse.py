"""AllSA XML parsing — root guard, empty feed, repeated <Features>, images order."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.allsa.parse import AllsaParseError, parse_feed

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/allsa/fixtures"


def test_parses_the_fixture_feed():
    result = parse_feed(FIXTURES.joinpath("feed.xml").read_bytes())
    assert len(result.properties) == 9
    first = result.properties[0]
    assert first.fields["Reference"] == "1604015"
    assert first.fields["Title"] == "Freehold"
    assert first.images == (
        "https://img.example.test/90000/1604015-a.jpg",
        "https://img.example.test/90000/1604015-b.jpg",
        "https://img.example.test/90000/1604015-c.jpg",
    )
    assert first.features == (("Floor_Size", "124"), ("Levies", "645"))


def test_empty_listings_is_not_an_error():
    result = parse_feed(FIXTURES.joinpath("empty.xml").read_bytes())
    assert result.properties == []
    assert result.duplicate_feature_elements == 0


def test_html_error_page_raises():
    with pytest.raises(AllsaParseError):
        parse_feed(FIXTURES.joinpath("runtime_error.html").read_bytes())


def test_wrong_root_tag_raises():
    with pytest.raises(AllsaParseError, match="root tag"):
        parse_feed(b"<?xml version='1.0'?><Properties><Property/></Properties>")


def test_utf8_bom_is_tolerated():
    body = "﻿<?xml version='1.0'?><Listings><Property><Reference>1</Reference>".encode()
    body += b"<Heading>x</Heading></Property></Listings>"
    result = parse_feed(body)
    assert result.properties[0].fields["Reference"] == "1"


def test_repeated_feature_tags_collapse_first_wins():
    xml = (
        "<Listings><Property><Reference>6004</Reference><Heading>h</Heading>"
        "<Features>"
        "<Bedrooms>4</Bedrooms><Bathrooms>3</Bathrooms>"
        "<Bedrooms>9</Bedrooms><Bedrooms>9</Bedrooms><Bathrooms>9</Bathrooms>"
        "</Features></Property></Listings>"
    )
    result = parse_feed(xml)
    prop = result.properties[0]
    assert prop.features == (("Bedrooms", "4"), ("Bathrooms", "3"))
    assert prop.duplicate_feature_elements == 3
    assert result.duplicate_feature_elements == 3
