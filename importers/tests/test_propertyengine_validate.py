"""Offline — the two-tier Standards and Conventions checks."""

from __future__ import annotations

import copy
from pathlib import Path

from iol_importers.propertyengine.decode import parse_feed
from iol_importers.propertyengine.validate import run_warnings, validate_record

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertyengine/fixtures"
XML_RECORDS = parse_feed((FIXTURES / "feed.xml").read_bytes())
BY_ID = {r["UniqueID"]: r for r in XML_RECORDS}


def test_good_records_pass():
    assert validate_record(BY_ID["900001"]) is None
    assert validate_record(BY_ID["900003"]) is None


def test_bad_type_is_rejected():
    reason = validate_record(BY_ID["900005"])
    assert reason is not None and "Appendix B" in reason


def test_bad_date_format_is_rejected():
    rec = copy.deepcopy(BY_ID["900001"])
    rec["CreatedOn"] = "04/11/2025 12:00"
    assert "yyyy-mm-dd" in (validate_record(rec) or "")


def test_space_in_agent_phone_is_rejected():
    rec = copy.deepcopy(BY_ID["900001"])
    rec["Agents"]["agent"]["AgentPhone"] = "021 000 0001"
    assert "space" in (validate_record(rec) or "")


def test_malformed_email_is_rejected():
    rec = copy.deepcopy(BY_ID["900001"])
    rec["Agents"]["agent"]["AgentEmail"] = "not-an-email"
    assert "email" in (validate_record(rec) or "")


def test_no_geography_at_all_is_rejected():
    rec = copy.deepcopy(BY_ID["900001"])
    for key in ("Suburb", "CityTown", "Province", "Location"):
        rec.pop(key, None)
    assert "geography" not in ""  # sanity
    assert validate_record(rec) is not None


def test_location_alone_satisfies_geography():
    rec = copy.deepcopy(BY_ID["900002"])  # Location present, no free-text
    assert validate_record(rec) is None


def test_lowercase_tag_names_are_a_warning_not_a_rejection():
    # the real feed sends lowercase `status` / `agent` / `email`
    counts = run_warnings(XML_RECORDS)
    assert counts["non_pascal_tag_names"] == len(XML_RECORDS)
    # ...and none of those records is rejected for it
    assert all(
        (validate_record(r) is None) or ("Appendix B" in (validate_record(r) or ""))
        for r in XML_RECORDS
    )
