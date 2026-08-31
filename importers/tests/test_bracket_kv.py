"""The shared bracket-KV parser against the three real vendor extracts + edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.bracket_kv import BracketRecord, iter_records, parse, parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "bracket_kv"


def _load(name: str) -> list[BracketRecord]:
    return parse_file(FIXTURES / f"{name}.txt")


# --- the three real extracts ------------------------------------------------


def test_rt3_round_trips():
    recs = _load("rt3")
    assert [len(r) for r in recs] == [20, 35]

    r0 = recs[0]
    assert r0.get("Reference") == "1289051"
    assert r0.get_all("Image_URL") == [
        "http://s3-eu-west-1.amazonaws.com/rawson-ire/67a50635-359a-47f5-b450-5ec2e76ae23e.jpg",
        "http://s3-eu-west-1.amazonaws.com/rawson-ire/e6763bfc-f623-46ed-8848-12a6290d610b.jpg",
        "http://s3-eu-west-1.amazonaws.com/rawson-ire/54bb90f5-f33e-4bc6-827d-6aae5236cbe3.jpg",
    ]
    # value keeps its interior '/'  (R120/m², 149.98m²) and the delimiter '/' only
    assert r0.get("GPS") == "-25.87711087,28.17500169"
    assert r0.get("Details_URL") == "https://rawson.co.za/p/1289051"

    r1 = recs[1]
    assert len(r1.get_all("Image_URL")) == 3
    # [[Address:...]] ends with a bare ']]' — the optional trailing slash is absent
    assert r1.get("Address") == "26 Camp Street, Cullinan, Cullinan, Gauteng"

    desc = r1.get("Description")
    assert desc is not None
    assert desc.startswith("This immaculate property is based in the exclusive Cullinan")
    assert desc.rstrip().endswith("Contact the agent now.")
    assert desc == desc.strip()  # ends trimmed
    assert "\n\n" in desc  # interior paragraph break preserved
    assert "[[" not in desc  # the next pair did not leak in


def test_myroof_round_trips():
    recs = _load("myroof")
    assert [len(r) for r in recs] == [27, 31]

    r0 = recs[0]
    assert len(r0.get_all("Image_URL")) == 3
    # single-line value: only the terminator '/' is dropped, the URL's own '/' stays
    assert r0.get("Description") == (
        "To view more details, photos and floor plans for this property "
        "please go to https://www.myroof.co.za/MR149308"
    )
    assert r0.get("Details_URL") == (
        "https://www.myroof.co.za/MR149308-3-Bedroom-2-Bathroom-North-West"
    )

    assert recs[1].get("GPS") == ","  # the "no coordinates" sentinel, kept verbatim


def test_propertypost_round_trips():
    recs = _load("propertypost")
    assert [len(r) for r in recs] == [29, 41]

    r0 = recs[0]
    assert r0.get("Features_Description") == ""  # empty value is kept, not dropped
    assert ("Features_Description", "") in r0.pairs
    desc = r0.get("Description")
    assert desc is not None
    assert desc.startswith("Warehouse space available for rent on the Bultfontein")
    assert desc.rstrip().endswith("Flexible rental terms.")
    assert desc == desc.strip()

    assert len(recs[1].get_all("Image_URL")) == 3


@pytest.mark.parametrize("name", ["rt3", "myroof", "propertypost"])
def test_every_extract_has_two_records_and_no_bracket_leakage(name):
    recs = _load(name)
    assert len(recs) == 2
    for rec in recs:
        for key, value in rec.pairs:
            assert key
            assert "[[" not in key
            assert "]]" not in key
            assert "]]" not in value


# --- documented behaviour not covered by the trimmed fixtures ---------------


def test_trailing_listing_start_padding_yields_no_records():
    doc = "[[Listing_Start]]\n[[Reference:1/]]\n[[Listing_End]]\n" + "[[Listing_Start]]\n" * 200
    recs = parse(doc)
    assert len(recs) == 1
    assert recs[0].get("Reference") == "1"


def test_optional_trailing_slash():
    recs = parse("[[Listing_Start]]\n[[onshowdate:2026-08-29]]\n[[Listing_End]]")
    assert recs[0].pairs == (("onshowdate", "2026-08-29"),)


def test_stray_field_outside_a_record_is_ignored():
    doc = "[[SomeHeaderField:ignored/]]\n[[Listing_Start]]\n[[Reference:1/]]\n[[Listing_End]]"
    recs = parse(doc)
    assert len(recs) == 1
    assert recs[0].keys() == ["Reference"]


def test_second_listing_start_discards_the_partial_record():
    doc = (
        "[[Listing_Start]]\n[[Reference:orphan/]]\n"
        "[[Listing_Start]]\n[[Reference:kept/]]\n[[Listing_End]]"
    )
    recs = parse(doc)
    assert [r.get("Reference") for r in recs] == ["kept"]


def test_empty_value_is_preserved():
    recs = parse("[[Listing_Start]]\n[[Features_Description:/]]\n[[Listing_End]]")
    assert recs[0].pairs == (("Features_Description", ""),)


def test_empty_start_end_pair_is_an_empty_record():
    recs = parse("[[Listing_Start]]\n[[Listing_End]]")
    assert len(recs) == 1
    assert len(recs[0]) == 0
    assert not recs[0]


def test_crlf_and_bom_parse_identically_to_lf():
    lf = "[[Listing_Start]]\n[[Area:Centurion/]]\n[[Description:one\n\ntwo/]]\n[[Listing_End]]"
    crlf = "﻿" + lf.replace("\n", "\r\n")
    assert (
        parse(lf)[0].pairs
        == parse(crlf)[0].pairs
        == (
            ("Area", "Centurion"),
            ("Description", "one\n\ntwo"),
        )
    )


def test_multiline_value_terminated_by_next_pair_when_feed_omits_the_closer():
    # malformed: Description never closes; the next well-formed pair still parses
    doc = "[[Listing_Start]]\n[[Description:line one\nline two\n[[Heading:H/]]\n[[Listing_End]]"
    rec = parse(doc)[0]
    assert rec.get("Heading") == "H"
    assert rec.get("Description") == "line one\nline two"


def test_value_with_internal_slash_on_one_line():
    recs = parse("[[Listing_Start]]\n[[Details_URL:https://x/y/z/]]\n[[Listing_End]]")
    assert recs[0].get("Details_URL") == "https://x/y/z"


def test_bracket_record_accessors():
    rec = BracketRecord(
        (("Image_URL", "a"), ("Reference", "1"), ("Image_URL", "b"), ("Image_URL", "c"))
    )
    assert rec.get("Image_URL") == "a"
    assert rec.get("Missing") is None
    assert rec.get_all("Image_URL") == ["a", "b", "c"]
    assert rec.keys() == ["Image_URL", "Reference", "Image_URL", "Image_URL"]
    assert rec.as_dict() == {"Image_URL": ["a", "b", "c"], "Reference": ["1"]}
    assert list(rec) == list(rec.pairs)
    assert len(rec) == 4


def test_iter_records_is_lazy():
    doc = (
        "[[Listing_Start]]\n[[A:1/]]\n[[Listing_End]]\n[[Listing_Start]]\n[[B:2/]]\n[[Listing_End]]"
    )
    gen = iter_records(doc)
    assert next(gen).get("A") == "1"
    assert next(gen).get("B") == "2"


def test_parse_file_missing_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        parse_file(tmp_path / "nope.txt")
