"""Opt-in live test — a real MyRoof fetch. Skipped unless MYROOF_LIVE_TOKEN is set.

    MYROOF_LIVE_TOKEN=<token> uv run --project importers pytest -m live -k myroof

No database writes.
"""

from __future__ import annotations

import os

import pytest

from iol_importers.bracket_kv import parse
from iol_importers.myroof.client import MyroofClient
from iol_importers.myroof.map import to_import_record

pytestmark = pytest.mark.live

_TOKEN = os.environ.get("MYROOF_LIVE_TOKEN")


@pytest.fixture
def token() -> str:
    if not _TOKEN:
        pytest.skip("MYROOF_LIVE_TOKEN not set")
    return _TOKEN


def test_real_feed_parses_and_maps(token):
    client = MyroofClient()
    try:
        body = client.fetch(token)
    finally:
        client.close()

    records = parse(body)
    assert len(records) >= 1

    for rec in records:
        out, _ = to_import_record(rec)
        assert out["vendor_listing_id"]
        assert "Repossession" in out["features"]
