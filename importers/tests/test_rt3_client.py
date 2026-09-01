"""RT3 client — per-province URL, redirect follow, 429/5xx retry, body guard."""

from __future__ import annotations

import pytest

from iol_importers.rt3.client import Rt3APIError, Rt3Client
from rt3_mock import (
    BASE_URL,
    mock_transport,
    seen_urls,
    set_body,
    set_status,
    set_transient_5xx,
    set_transient_429,
)


def _client(**kw):
    return Rt3Client(transport=mock_transport(), retry_base_delay=0.0, **kw)


def _url(province: str) -> str:
    return f"{BASE_URL}/iol-{province}.txt"


def test_fetch_builds_the_province_url_and_returns_the_feed():
    body = _client().fetch(_url("Gauteng"))
    assert b"[[Listing_Start]]" in body
    assert seen_urls()[-1] == _url("Gauteng")


def test_transient_5xx_is_retried_then_succeeds():
    client = _client()
    set_transient_5xx(2)
    assert b"[[Listing_Start]]" in client.fetch(_url("Gauteng"))


def test_rate_limit_429_is_retried_then_succeeds():
    client = _client()
    set_transient_429(2)
    assert b"[[Listing_Start]]" in client.fetch(_url("Gauteng"))


def test_exhausted_retries_raise():
    client = _client(max_retries=2)
    set_transient_5xx(5)
    with pytest.raises(Rt3APIError, match="retries exhausted"):
        client.fetch(_url("Gauteng"))


def test_non_feed_body_raises():
    client = _client()
    set_body(b"<!DOCTYPE html><html><body>404</body></html>", content_type="text/html")
    with pytest.raises(Rt3APIError, match="not bracket-KV"):
        client.fetch(_url("Gauteng"))


def test_4xx_raises():
    client = _client()
    set_status(404)
    with pytest.raises(Rt3APIError, match="HTTP 404"):
        client.fetch(_url("Gauteng"))
