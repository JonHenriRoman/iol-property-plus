"""Opt-in live test — a real AllSA fetch. Skipped unless ALLSA_LIVE_AGENCY_ID is set.

    ALLSA_LIVE_AGENCY_ID=10173 uv run --project importers pytest -m live -k allsa

No database writes.
"""

from __future__ import annotations

import os

import pytest

from iol_importers.allsa.client import AllsaClient
from iol_importers.allsa.map import to_import_record
from iol_importers.allsa.parse import parse_feed

pytestmark = pytest.mark.live

_AGENCY = os.environ.get("ALLSA_LIVE_AGENCY_ID")


@pytest.fixture
def agency_id() -> str:
    if not _AGENCY:
        pytest.skip("ALLSA_LIVE_AGENCY_ID not set")
    return _AGENCY


def test_real_feed_parses_and_maps(agency_id):
    client = AllsaClient()
    try:
        body = client.fetch(agency_id)
    finally:
        client.close()

    result = parse_feed(body)
    assert len(result.properties) >= 1

    branches = set()
    for prop in result.properties:
        record, _ = to_import_record(prop)
        assert record["vendor_listing_id"]
        branches.add(prop.fields.get("BranchId", ""))

    # The real 10173 feed spans four BranchIds; any real feed has at least one.
    assert branches
