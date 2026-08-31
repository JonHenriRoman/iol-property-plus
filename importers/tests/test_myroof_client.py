"""MyRoof client — token in the path only, redaction, retry, body guard."""

from __future__ import annotations

import logging

import pytest

from iol_importers.myroof.client import MyroofAPIError, MyroofClient
from myroof_mock import BASE_URL, mock_transport, seen_urls, set_body, set_status, set_transient_5xx

_TOKEN = "sekrit-franchise-token"


def _client(**kw):
    return MyroofClient(base_url=BASE_URL, transport=mock_transport(), retry_base_delay=0.0, **kw)


def test_fetch_puts_the_token_in_the_path():
    body = _client().fetch(_TOKEN)
    assert b"[[Listing_Start]]" in body
    assert seen_urls()[-1] == f"{BASE_URL}/{_TOKEN}"


def test_token_never_appears_in_repr_or_errors(caplog):
    client = _client()
    assert _TOKEN not in repr(client)
    set_status(404)
    with (
        caplog.at_level(logging.DEBUG, logger="iol_importers.myroof"),
        pytest.raises(MyroofAPIError) as excinfo,
    ):
        client.fetch(_TOKEN)
    assert _TOKEN not in str(excinfo.value)
    assert _TOKEN not in caplog.text


def test_transient_5xx_is_retried_then_succeeds():
    client = _client()
    set_transient_5xx(2)
    assert b"[[Listing_Start]]" in client.fetch(_TOKEN)


def test_exhausted_retries_raise():
    client = _client(max_retries=2)
    set_transient_5xx(5)
    with pytest.raises(MyroofAPIError, match="retries exhausted"):
        client.fetch(_TOKEN)


def test_non_feed_body_raises():
    client = _client()
    set_body(b"<!DOCTYPE html><html><body>Not found</body></html>", content_type="text/html")
    with pytest.raises(MyroofAPIError, match="not bracket-KV"):
        client.fetch(_TOKEN)


def test_4xx_raises_without_the_token():
    client = _client()
    set_status(403)
    with pytest.raises(MyroofAPIError, match="HTTP 403"):
        client.fetch(_TOKEN)
