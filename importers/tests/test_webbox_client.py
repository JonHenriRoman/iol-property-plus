"""Webbox client — siteid+key in the path, redaction, retry, body guard."""

from __future__ import annotations

import logging

import pytest

from iol_importers.webbox.client import WebboxAPIError, WebboxClient
from webbox_mock import BASE_URL, mock_transport, seen_urls, set_body, set_status, set_transient_5xx

_SITEID = "612"
_KEY = "sekrit-security-key"


def _client(**kw):
    return WebboxClient(base_url=BASE_URL, transport=mock_transport(), retry_base_delay=0.0, **kw)


def test_fetch_puts_siteid_and_key_in_the_path():
    body = _client().fetch(_SITEID, _KEY)
    assert b"<property" in body.lower()
    url = seen_urls()[-1]
    assert f"/siteid/{_SITEID}/securitykey/{_KEY}/feed.xml" in url


def test_key_never_appears_in_repr_or_errors(caplog):
    client = _client()
    assert _KEY not in repr(client)
    set_status(403)
    with (
        caplog.at_level(logging.DEBUG, logger="iol_importers.webbox"),
        pytest.raises(WebboxAPIError) as excinfo,
    ):
        client.fetch(_SITEID, _KEY)
    assert _KEY not in str(excinfo.value)
    assert _KEY not in caplog.text


def test_transient_5xx_is_retried_then_succeeds():
    client = _client()
    set_transient_5xx(2)
    assert b"<property" in client.fetch(_SITEID, _KEY).lower()


def test_exhausted_retries_raise():
    client = _client(max_retries=2)
    set_transient_5xx(5)
    with pytest.raises(WebboxAPIError, match="retries exhausted"):
        client.fetch(_SITEID, _KEY)


def test_non_feed_body_raises():
    client = _client()
    set_body(b"<html><body>Access denied</body></html>", content_type="text/html")
    with pytest.raises(WebboxAPIError, match="not Webbox XML"):
        client.fetch(_SITEID, _KEY)


def test_4xx_raises_without_the_key():
    client = _client()
    set_status(404)
    with pytest.raises(WebboxAPIError, match="HTTP 404"):
        client.fetch(_SITEID, _KEY)
