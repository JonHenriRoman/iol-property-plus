"""Opt-in live test — a real signed call to the Fusion FeedStore.

Skipped unless FUSION_CLIENT_ID / FUSION_PASSWORD resolve. Read-only: it never
acknowledges a commitToken and never issues RequestSnapshot against a
non-QA host, so it cannot advance or reset the real sync cursor. No DB writes.

    uv run --project importers pytest -m live
"""

from __future__ import annotations

import pytest

from iol_importers.config import resolve_fusion_credentials
from iol_importers.fusion.client import FusionClient

pytestmark = pytest.mark.live


@pytest.fixture
def client(tmp_path):
    if resolve_fusion_credentials() is None:
        pytest.skip("FUSION_CLIENT_ID / FUSION_PASSWORD not set")
    with FusionClient(state_dir=tmp_path) as c:
        yield c


def test_get_client_state(client):
    state = client.get_client_state()
    assert state.client_id
    assert state.type in ("PortalSync", "AgencySync", "NationalSync", None)


def test_get_changes_head_parses(client):
    # commitToken omitted -> replays the current head batch (or <Changes/> when the
    # queue is empty). Never acknowledges, so the real cursor does not move.
    batch = client.get_changes(None)
    assert batch.client_id is not None or batch.drained
    for event in batch.events:
        assert event.object_type in ("Office", "Agent", "Listing", "Development", "AreaTree")


def test_request_snapshot_only_against_qa(client):
    if "qa" not in resolve_fusion_credentials().base_url.lower():
        pytest.skip("not pointed at the QA host — RequestSnapshot would reset the real cursor")
    assert client.request_snapshot() in (None, "ExistingSnapshotAborted", "ExistingRollbackAborted")
    batch = client.get_changes(None)
    assert batch.begin_snapshot is not None or batch.drained
