"""Offline tests for the PropCtrl client — fixture-backed MockTransport, no network."""

from __future__ import annotations

import base64
import logging
import stat

import pytest

from iol_importers.config import PropctrlCredentials
from iol_importers.propctrl.client import PropctrlAuthError, PropctrlClient
from propctrl_mock import load_listings, mock_transport

CREDS = PropctrlCredentials(
    username="apiuser@example.test",
    password="s3cret-do-not-log",
    base_url="https://api.propctrl.com",
)


def _client(tmp_path) -> PropctrlClient:
    return PropctrlClient(credentials=CREDS, transport=mock_transport(), state_dir=tmp_path)


def test_echo_verifies_the_credentials(tmp_path):
    assert _client(tmp_path).echo() is True


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.setattr(
        "iol_importers.propctrl.client.resolve_propctrl_credentials", lambda: None
    )
    client = PropctrlClient.__new__(PropctrlClient)
    client._credentials = None
    with pytest.raises(PropctrlAuthError, match="PROPCTRL_API_USERNAME"):
        _ = client._creds


def test_fetch_changes_returns_items_and_cursor(tmp_path):
    items, next_from_date = _client(tmp_path).fetch_changes("2020-01-01T00:00:00Z")
    assert items
    assert next_from_date
    assert {i["changeType"] for i in items} <= {"New", "Modified", "Removed"}


def test_iter_listings_dedupes_and_returns_every_id(tmp_path):
    client = _client(tmp_path)
    ids = [x["listingId"] for x in load_listings()]
    assert len(ids) > 10  # fixture has ~20
    got = list(client.iter_listings(ids + ids))  # duplicates collapse
    assert len(got) == len(ids)
    assert {x["listingId"] for x in got} == set(ids)


def test_iter_listings_never_sends_more_than_ten_ids(tmp_path, monkeypatch):
    seen: list[int] = []
    real = PropctrlClient._get

    def spy(self, path, *, params=None):
        if path == "/listing/v1/listings":
            seen.append(len(params["listingIds"]))
        return real(self, path, params=params)

    monkeypatch.setattr(PropctrlClient, "_get", spy)
    ids = [x["listingId"] for x in load_listings()]
    list(_client(tmp_path).iter_listings(ids))
    assert seen
    assert max(seen) <= 10


def test_entity_lookups_are_cached(tmp_path):
    client = _client(tmp_path)
    sid = next(x["suburbId"] for x in load_listings() if x.get("suburbId"))
    first = client.get_suburbs([sid])
    assert client.get_suburbs([sid])[sid] is first[sid]  # same cached object


def test_checkpoint_round_trips_and_is_private(tmp_path):
    client = _client(tmp_path)
    assert client.load_checkpoint() is None
    client.save_checkpoint("2026-08-30T17:00:00Z")
    assert client.load_checkpoint() == "2026-08-30T17:00:00Z"
    text = (tmp_path / "checkpoint.json").read_text()
    assert stat.S_IMODE((tmp_path / "checkpoint.json").stat().st_mode) == 0o600
    assert "next_from_date" in text
    assert CREDS.password not in text


def test_credentials_never_appear_in_repr_or_logs(tmp_path, caplog):
    client = _client(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="iol_importers.propctrl"):
        client.echo()
        client.fetch_changes("2020-01-01T00:00:00Z")
    header = "Basic " + base64.b64encode(
        f"{CREDS.username}:{CREDS.password}".encode()
    ).decode()
    assert "auth=<set>" in repr(client)
    assert header not in repr(client)
    assert CREDS.password not in caplog.text
    assert header not in caplog.text
