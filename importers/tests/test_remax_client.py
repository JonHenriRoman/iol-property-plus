"""Offline tests for the RE/MAX client — fixture-backed MockTransport, no network."""

from __future__ import annotations

import logging

import pytest

from iol_importers.config import RemaxCredentials
from iol_importers.remax.client import RemaxAPIError, RemaxClient
from remax_mock import arm_transient_failure, mock_transport

CREDS = RemaxCredentials(
    access_key="AKIATEST0000000000EX",
    secret_key="do-not-log-this-secret-key-value-000000000",
    api_key="do-not-log-this-api-key-value-00000000000",
    base_url="https://ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com/feeds_default",
)


def _client(tmp_path, **kw) -> RemaxClient:
    return RemaxClient(
        credentials=CREDS,
        transport=mock_transport(),
        state_dir=tmp_path,
        retry_base_delay=0.0,
        **kw,
    )


def test_list_agent_ids_dedupes(tmp_path):
    ids = _client(tmp_path).list_agent_ids()
    assert ids == list(dict.fromkeys(ids))
    assert len(ids) >= 10


def test_double_encoded_envelope_is_decoded(tmp_path):
    offices = _client(tmp_path).list_office_ids()
    assert offices and all(isinstance(o, int) for o in offices)


def test_broken_lists_listings_raises(tmp_path):
    client = _client(tmp_path)
    with pytest.raises(RemaxAPIError):
        client._post("lists", {"listings": True})


def test_transient_504_is_retried(tmp_path):
    arm_transient_failure("lists")
    offices = _client(tmp_path).list_office_ids()  # 504 then 200
    assert offices


def test_retries_exhausted_raises(tmp_path):
    client = _client(tmp_path, max_retries=1)
    arm_transient_failure("lists")
    with pytest.raises(RemaxAPIError, match="retries exhausted"):
        client.list_office_ids()


def test_pagination_follows_has_next_page(tmp_path):
    client = _client(tmp_path)
    deleted = list(client.iter_deleted_listings())
    changed = list(client.iter_changed_listings("2026-08-28 00:00:00"))
    assert len(deleted) >= 6  # p0 + p1
    assert len(changed) >= 4  # p0 + p1


def test_max_pages_bounds_the_walk(tmp_path):
    one = list(_client(tmp_path).iter_deleted_listings(max_pages=1))
    allp = list(_client(tmp_path).iter_deleted_listings())
    assert 0 < len(one) < len(allp)


def test_credentials_never_appear_in_repr_or_logs(tmp_path, caplog):
    client = _client(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="iol_importers.remax"):
        client.list_office_ids()
        list(client.iter_changed_listings("2026-08-28 00:00:00"))
    assert "creds=<set>" in repr(client)
    assert CREDS.secret_key not in repr(client)
    assert CREDS.secret_key not in caplog.text
    assert CREDS.api_key not in caplog.text
