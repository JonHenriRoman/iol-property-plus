"""Offline unit tests — FusionClient against the mock transport."""

from __future__ import annotations

import logging

import httpx
import pytest

from fusion_mock import load, mock_transport, snapshot_transport
from iol_importers.config import FusionCredentials
from iol_importers.fusion.client import FusionAPIError, FusionClient
from iol_importers.fusion.parse import FusionException

CREDS = FusionCredentials(
    client_id=458, password="do-not-log-this-secret", base_url="https://fusion.test/v1/sync"
)


def _client(transport, **kw) -> FusionClient:
    return FusionClient(
        credentials=CREDS, transport=transport, retry_base_delay=0.0, housekeeping_delay=0.0, **kw
    )


def test_get_changes_drains_sequence_with_acknowledgement():
    transport, server = snapshot_transport()
    with _client(transport) as client:
        b1 = client.get_changes(None)
        assert b1.commit_token == "snap-token-1"
        b2 = client.get_changes(b1.commit_token)
        assert b2.commit_token == "snap-token-2"
        b3 = client.get_changes(b2.commit_token)
        assert b3.end_snapshot is True
        b4 = client.get_changes(b3.commit_token)
        assert b4.drained is True
    assert server.get_changes_calls == [None, "snap-token-1", "snap-token-2", "snap-token-3"]


def test_omitting_token_replays_current_batch():
    transport, _ = snapshot_transport()
    with _client(transport) as client:
        first = client.get_changes(None)
        again = client.get_changes(None)
    assert first.commit_token == again.commit_token == "snap-token-1"


def test_security_params_on_every_request_including_retries():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        if len(seen) < 3:
            return httpx.Response(200, text=load("exc_housekeeping"))
        return httpx.Response(200, text=load("drained"))

    with _client(httpx.MockTransport(handler)) as client:
        client.get_changes(None)
    assert len(seen) == 3
    assert all({"clientId", "timeStamp", "salt", "digest"} <= set(p) for p in seen)
    # a fresh salt per attempt
    assert len({p["salt"] for p in seen}) == 3


def test_housekeeping_then_success_is_retried():
    transport, server = snapshot_transport()
    server.arm_exception("exc_housekeeping")
    with _client(transport) as client:
        batch = client.get_changes(None)
    assert batch.commit_token == "snap-token-1"


def test_invalid_commit_token_propagates_with_correct_token():
    transport, _ = snapshot_transport()
    with _client(transport) as client, pytest.raises(FusionException) as exc:
        client.get_changes("a-stale-token")
    assert exc.value.type == "InvalidCommitToken"
    assert exc.value.attrib["commitToken"] == "snap-token-1"


def test_request_snapshot_returns_warning():
    transport, server = snapshot_transport()
    with _client(transport) as client:
        assert client.request_snapshot() == "ExistingSnapshotAborted"
    assert server.snapshot_requested == 1


def test_get_client_state():
    transport, _ = snapshot_transport()
    with _client(transport) as client:
        state = client.get_client_state()
    assert state.name == "IOL"


def test_5xx_is_retried_then_raises():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="upstream down")

    with (
        _client(httpx.MockTransport(handler), max_retries=3) as client,
        pytest.raises(FusionAPIError),
    ):
        client.get_changes(None)
    assert calls["n"] == 3


def test_credentials_never_in_repr_or_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="iol_importers.fusion")
    transport, _ = mock_transport(("drained",))
    with _client(transport) as client:
        client.get_changes(None)
        text = repr(client)
    assert "do-not-log-this-secret" not in text
    assert "do-not-log-this-secret" not in caplog.text
    assert "client_id=458" in text


def test_state_round_trip(tmp_path):
    from iol_importers.fusion.client import FusionState, SnapshotState

    transport, _ = snapshot_transport()
    client = _client(transport, state_dir=tmp_path)
    client.save_state(
        FusionState(commit_token="tok", snapshot=SnapshotState(True, ("Listings",)), updated_at="x")
    )
    loaded = client.load_state()
    assert loaded.commit_token == "tok"
    assert loaded.snapshot.in_progress is True
    assert loaded.snapshot.types == ("Listings",)
    client.close()
