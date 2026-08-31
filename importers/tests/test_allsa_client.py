"""AllSA client — query params, no auth, retry, HTML-body guard."""

from __future__ import annotations

import pytest

from allsa_mock import (
    BASE_URL,
    fixture_bytes,
    mock_transport,
    seen_headers,
    seen_params,
    set_body,
    set_status,
    set_transient_5xx,
)
from iol_importers.allsa.client import AllsaAPIError, AllsaClient


def _client(**kw):
    return AllsaClient(base_url=BASE_URL, transport=mock_transport(), retry_base_delay=0.0, **kw)


def test_fetch_sends_agencyid_and_no_auth():
    body = _client().fetch("10173")
    assert body.lstrip().startswith(b"<?xml") or b"<Listings" in body
    assert seen_params()[-1] == {"agencyid": "10173"}
    assert "authorization" not in {k.lower() for k in seen_headers()[-1]}


def test_transient_5xx_is_retried_then_succeeds():
    c = _client()
    set_transient_5xx(2)
    body = c.fetch("10173")
    assert b"<Listings" in body


def test_exhausted_retries_raise():
    c = _client(max_retries=2)
    set_transient_5xx(5)
    with pytest.raises(AllsaAPIError, match="retries exhausted"):
        c.fetch("10173")


def test_html_body_behind_200_raises():
    c = _client()
    set_body(fixture_bytes("runtime_error.html"), content_type="text/html")
    with pytest.raises(AllsaAPIError, match="non-XML body"):
        c.fetch("")


def test_4xx_raises_immediately():
    c = _client()
    set_status(404)
    with pytest.raises(AllsaAPIError, match="HTTP 404"):
        c.fetch("10173")


def test_empty_listings_is_returned_not_raised():
    c = _client()
    set_body(fixture_bytes("empty.xml"))
    assert b"<Listings" in c.fetch("999999")
