"""Webbox XML stream-parse — outer forms, CDATA, empty elements, nesting."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.webbox.parse import WebboxParseError, parse_feed

FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/webbox/fixtures/feed.xml"
# sibling Go pack's real 3-property capture, if present
REAL = Path(__file__).resolve().parents[3] / "iol-property/packs/webbox/tests/sample.xml"

_BARE = b"""<property>
<reference>Z1</reference><listing-type>Sale</listing-type>
<heading><![CDATA[a & b]]></heading>
<price><amount/><currency>ZAR</currency></price>
<virtual-tour/><videos/>
<features><bedrooms>2</bedrooms><bedrooms>9</bedrooms></features>
<property-type>House</property-type>
</property>"""

_TWO_AGENCIES = b"""<?xml version="1.0"?><!DOCTYPE agencies SYSTEM "http://x/y.dtd">
<agencies>
<agency><agency-details><id>1</id><name>One</name></agency-details>
<properties><property><reference>A</reference><property-type>House</property-type></property></properties>
</agency>
<agency><agency-details><id>2</id><name>Two</name></agency-details>
<properties><property><reference>B</reference><property-type>House</property-type></property></properties>
</agency>
</agencies>"""


def test_wrapped_fixture_parses_with_agency_context():
    r = parse_feed(FIXTURE.read_bytes())
    assert r.outer_form == "wrapped"
    assert r.agencies_seen == 1
    assert len(r.properties) == 5
    for p in r.properties:
        assert p.agency.get("id") == "612"
        assert p.agency.get("name") == "Valuables Properties - Bellville"


def test_doctype_system_declaration_is_tolerated_and_cdata_unwrapped():
    r = parse_feed(FIXTURE.read_bytes())
    p1597 = next(p for p in r.properties if p.fields["reference"] == "1597")
    assert p1597.fields["address"] == "3 Jay road, Milnerton, Cape Town"  # CDATA
    assert p1597.fields["heading"].startswith("A furnished 2 bedroom")
    assert "Availability: 2025-05-01" in p1597.fields["description"]  # left in the free text


def test_bare_property_root_and_empty_elements():
    r = parse_feed(_BARE)
    assert r.outer_form == "bare-property"
    assert len(r.properties) == 1
    p = r.properties[0]
    assert p.agency == {}
    assert p.nested["price"]["amount"] == ""  # <amount/> -> ""
    assert p.fields["virtual-tour"] == ""  # <virtual-tour/> -> ""
    assert p.fields["heading"] == "a & b"  # CDATA entity survives


def test_repeated_feature_tag_dropped_first_wins_with_a_tally():
    r = parse_feed(_BARE)
    p = r.properties[0]
    assert dict(p.features)["bedrooms"] == "2"  # first wins, not "9"
    assert p.duplicate_feature_elements == 1


def test_two_agency_blocks_each_carry_their_own_context():
    r = parse_feed(_TWO_AGENCIES)
    assert r.outer_form == "wrapped"
    assert r.agencies_seen == 2
    by_ref = {p.fields["reference"]: p for p in r.properties}
    assert by_ref["A"].agency["name"] == "One"
    assert by_ref["B"].agency["name"] == "Two"


def test_nested_blocks_and_agents_and_images():
    r = parse_feed(FIXTURE.read_bytes())
    p1531 = next(p for p in r.properties if p.fields["reference"] == "1531")
    assert p1531.nested["land-size"] == {
        "land-size-unit": "meters_squared",
        "land-size-value": "589",
    }
    assert [a["agent-id"] for a in p1531.agents] == ["20733", "20734"]
    assert len(p1531.images) == 3
    assert p1531.videos == ()  # <videos/> empty


def test_malformed_body_raises():
    with pytest.raises(WebboxParseError):
        parse_feed(b"<agencies><agency><oops")


@pytest.mark.skipif(not REAL.exists(), reason="sibling Go pack sample.xml not present")
def test_real_go_pack_sample_parses():
    r = parse_feed(REAL.read_bytes())
    assert r.outer_form == "wrapped"
    assert len(r.properties) == 3
    assert {p.fields["reference"] for p in r.properties} == {"1597", "1531", "2678"}
