"""Opt-in live test — one real RT3 province fetch. Skipped unless
RT3_LIVE_PROVINCE_URL is set.

    RT3_LIVE_PROVINCE_URL=https://webservices.rawsonproperties.co.za/iol-Gauteng.txt \\
        uv run --project importers pytest -m live -k rt3

No database writes.
"""

from __future__ import annotations

import os

import pytest

from iol_importers.bracket_kv import parse
from iol_importers.rt3.client import Rt3Client
from iol_importers.rt3.map import to_import_record

pytestmark = pytest.mark.live

_URL = os.environ.get("RT3_LIVE_PROVINCE_URL")


@pytest.fixture
def province_url() -> str:
    if not _URL:
        pytest.skip("RT3_LIVE_PROVINCE_URL not set")
    return _URL


def test_real_feed_parses_and_maps(province_url):
    client = Rt3Client()
    try:
        body = client.fetch(province_url)
    finally:
        client.close()

    records = parse(body)
    assert len(records) >= 1

    branches: set[str] = set()
    agent_hist: dict[int, int] = {}
    for rec in records:
        out, _ = to_import_record(rec, province="live")
        assert out["vendor_listing_id"]
        assert out["listing_type"] in {"For Sale", "To Let"}
        if out["agency_vendor_id"]:
            branches.add(out["agency_vendor_id"])
        n = len(out.get("rt3_agents", []) or [])
        agent_hist[n] = agent_hist.get(n, 0) + 1

    print(f"\ndistinct Branch_ID: {len(branches)}   agent-count histogram: {agent_hist}")
