"""Opt-in live test — real SigV4-signed calls to the RE/MAX feed.

Not in the default run. Needs REMAX_ACCESS_KEY / REMAX_SECRET_KEY / REMAX_API_KEY
in the environment or .env.local.

    uv run --project importers pytest -m live
"""

from __future__ import annotations

import pytest

from iol_importers.config import resolve_remax_credentials
from iol_importers.remax.client import RemaxClient

pytestmark = pytest.mark.live


@pytest.fixture
def client(tmp_path):
    if resolve_remax_credentials() is None:
        pytest.skip("RE/MAX credentials not configured")
    with RemaxClient(state_dir=tmp_path) as c:
        yield c


def test_signed_lists_then_one_page_of_each_path(client):
    office_ids = client.list_office_ids()
    assert isinstance(office_ids, list) and office_ids  # a signed /lists call succeeded

    agent_ids = client.list_agent_ids()
    assert agent_ids == list(dict.fromkeys(agent_ids))  # deduped

    changed = list(client.iter_changed_listings("2026-08-28 00:00:00", max_pages=1))
    assert isinstance(changed, list)

    deleted = list(client.iter_deleted_listings(max_pages=1))
    assert isinstance(deleted, list)

    if changed:
        detail = client.get_listing(changed[0]["property_id"])
        assert detail is None or "features" in detail
