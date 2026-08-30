"""Opt-in live test — real calls to the PropCtrl Listing Service.

Not in the default run. Needs PROPCTRL_API_USERNAME / PROPCTRL_API_PASSWORD in
the environment or .env.local.

    uv run --project importers pytest -m live
"""

from __future__ import annotations

import pytest

from iol_importers.config import resolve_propctrl_credentials
from iol_importers.propctrl.client import PropctrlClient

pytestmark = pytest.mark.live


@pytest.fixture
def client(tmp_path):
    if resolve_propctrl_credentials() is None:
        pytest.skip("PropCtrl credentials not configured")
    with PropctrlClient(state_dir=tmp_path) as c:
        yield c


def test_echo_then_changes_then_one_bounded_listing_batch(client):
    assert client.echo() is True

    items, next_from_date = client.fetch_changes("2026-08-28T00:00:00Z")
    assert isinstance(items, list)
    assert next_from_date

    ids = [i["id"] for i in items if i["changeType"] in ("New", "Modified")][:10]
    if ids:
        listings = list(client.iter_listings(ids))
        assert isinstance(listings, list)
        assert all("listingId" in x for x in listings)
