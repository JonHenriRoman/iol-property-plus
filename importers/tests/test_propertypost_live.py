"""Opt-in live test — a real PropertyPost fetch. Skipped unless
PROPERTYPOST_LIVE_FEED_URL is set.

    PROPERTYPOST_LIVE_FEED_URL=http://lms.propertypost.co.za/BstProperties.txt \\
        uv run --project importers pytest -m live -k propertypost

No database writes.
"""

from __future__ import annotations

import os

import pytest

from iol_importers.bracket_kv import parse
from iol_importers.propertypost.client import PropertypostClient
from iol_importers.propertypost.map import to_import_record

pytestmark = pytest.mark.live

_URL = os.environ.get("PROPERTYPOST_LIVE_FEED_URL")


@pytest.fixture
def feed_url() -> str:
    if not _URL:
        pytest.skip("PROPERTYPOST_LIVE_FEED_URL not set")
    return _URL


def test_real_feed_parses_and_maps(feed_url):
    client = PropertypostClient()
    try:
        body = client.fetch(feed_url)
    finally:
        client.close()

    records = parse(body)
    assert len(records) >= 1

    branches = set()
    for rec in records:
        out, _ = to_import_record(rec)
        assert out["vendor_listing_id"]
        assert out["title"]
        assert out["listing_type"] in {"For Sale", "To Let"}
        if out["agency_vendor_id"]:
            branches.add(out["agency_vendor_id"])

    print(f"\ndistinct Branch_ID values: {sorted(branches)}")
