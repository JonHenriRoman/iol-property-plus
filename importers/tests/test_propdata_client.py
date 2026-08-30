"""Offline tests for the Propdata client — fixture-backed MockTransport, no network."""

from __future__ import annotations

import logging

import pytest

from iol_importers.config import PropdataCredentials
from iol_importers.propdata.client import PropdataAuthError, PropdataClient
from propdata_mock import RENEWED_TOKEN, mock_transport

CREDS = PropdataCredentials(
    username="apiuser",
    password="s3cret-do-not-log",
    login_url="https://api-gw.propdata.net/users/public-api/login/",
)


def _client(tmp_path, site="harcourts.co.za") -> PropdataClient:
    return PropdataClient(
        site, credentials=CREDS, transport=mock_transport(), token_dir=tmp_path
    )


def test_authenticate_picks_the_token_for_the_configured_site(tmp_path):
    client = _client(tmp_path)
    client.authenticate()
    assert client._token == "__REDACTED_TOKEN__"  # fixture value
    assert (tmp_path / "token-harcourts.co.za.json").is_file()


def test_authenticate_unknown_site_raises(tmp_path):
    client = _client(tmp_path, site="nosuchsite.co.za")
    with pytest.raises(PropdataAuthError, match="no client for site"):
        client.authenticate()


def test_renew_reads_the_token_response_header(tmp_path):
    client = _client(tmp_path)
    client.authenticate()
    client.renew()
    assert client._token == RENEWED_TOKEN


def test_ensure_token_renews_a_stored_token(tmp_path):
    _client(tmp_path).authenticate()  # writes token-<site>.json
    client = _client(tmp_path)
    client.ensure_token()
    assert client._token == RENEWED_TOKEN  # renewed, not re-authenticated


def test_iter_listings_follows_pagination_to_the_end(tmp_path):
    client = _client(tmp_path)
    client.ensure_token()
    ids = [r["id"] for r in client.iter_listings("residential")]
    # page 1 (3) + page 2 (fixture) then next=null
    assert len(ids) >= 4
    assert len(ids) == len(set(ids))


def test_page_limit_stops_early(tmp_path):
    client = _client(tmp_path)
    client.ensure_token()
    one_page = list(client.iter_listings("residential", page_limit=1))
    assert len(one_page) == 3


def test_lookups_are_cached(tmp_path):
    client = _client(tmp_path)
    client.ensure_token()
    first = client.get_branch(1259)
    assert client.get_branch(1259) is first  # same cached dict object


def test_token_never_appears_in_repr_or_logs(tmp_path, caplog):
    client = _client(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="iol_importers.propdata"):
        client.ensure_token()
        list(client.iter_listings("commercial", page_limit=1))
    assert RENEWED_TOKEN not in repr(client)
    assert "token=<set>" in repr(client)
    assert RENEWED_TOKEN not in caplog.text
    assert CREDS.password not in caplog.text
