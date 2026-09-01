"""PropertyPost client — URL fetch, redirect follow, 429/5xx retry, body guard."""

from __future__ import annotations

import pytest

from iol_importers.propertypost.client import PropertypostAPIError, PropertypostClient
from propertypost_mock import (
    FEED_URL,
    mock_transport,
    seen_urls,
    set_body,
    set_status,
    set_transient_5xx,
    set_transient_429,
)


def _client(**kw):
    return PropertypostClient(transport=mock_transport(), retry_base_delay=0.0, **kw)


def test_fetch_gets_the_configured_url():
    body = _client().fetch(FEED_URL)
    assert b"[[Listing_Start]]" in body
    assert seen_urls()[-1] == FEED_URL


def test_transient_5xx_is_retried_then_succeeds():
    client = _client()
    set_transient_5xx(2)
    assert b"[[Listing_Start]]" in client.fetch(FEED_URL)


def test_rate_limit_429_is_retried_then_succeeds():
    client = _client()
    set_transient_429(2)
    assert b"[[Listing_Start]]" in client.fetch(FEED_URL)


def test_exhausted_retries_raise():
    client = _client(max_retries=2)
    set_transient_5xx(5)
    with pytest.raises(PropertypostAPIError, match="retries exhausted"):
        client.fetch(FEED_URL)


def test_non_feed_body_raises():
    client = _client()
    set_body(b"<!DOCTYPE html><html><body>Not found</body></html>", content_type="text/html")
    with pytest.raises(PropertypostAPIError, match="not bracket-KV"):
        client.fetch(FEED_URL)


def test_4xx_raises():
    client = _client()
    set_status(403)
    with pytest.raises(PropertypostAPIError, match="HTTP 403"):
        client.fetch(FEED_URL)
