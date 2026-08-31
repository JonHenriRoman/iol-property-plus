"""Offline — the feed client: optional auth, retries, redaction, --file."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from iol_importers.config import PropertyengineFeed
from iol_importers.propertyengine.client import (
    PropertyEngineAPIError,
    PropertyEngineAuthError,
    PropertyEngineClient,
)
from propertyengine_mock import (
    FEED_URL,
    mock_transport,
    set_status,
    set_transient_5xx,
)

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertyengine/fixtures"


def _client(feed: PropertyengineFeed | None, **kw) -> PropertyEngineClient:
    return PropertyEngineClient(
        feed=feed, transport=mock_transport(), retry_base_delay=0.0, **kw
    )


def test_no_authorization_header_when_token_unset():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"<listings/>")

    feed = PropertyengineFeed(FEED_URL, auth_token=None, auth_scheme="bearer")
    client = PropertyEngineClient(feed=feed, transport=httpx.MockTransport(handler))
    client.fetch()
    assert seen["auth"] is None
    client.close()


@pytest.mark.parametrize(
    ("scheme", "prefix"), [("bearer", "Bearer "), ("basic", "Basic ")]
)
def test_authorization_header_when_token_set(scheme, prefix):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"<listings/>")

    feed = PropertyengineFeed(FEED_URL, auth_token="s3cr3t-token", auth_scheme=scheme)
    client = PropertyEngineClient(feed=feed, transport=httpx.MockTransport(handler))
    client.fetch()
    assert seen["auth"] == f"{prefix}s3cr3t-token"
    client.close()


def test_401_and_403_raise_auth_error():
    feed = PropertyengineFeed(FEED_URL, auth_token="x", auth_scheme="bearer")
    for status in (401, 403):
        client = _client(feed)
        set_status(status)
        with pytest.raises(PropertyEngineAuthError):
            client.fetch()
        client.close()


def test_transient_5xx_is_retried_then_succeeds():
    feed = PropertyengineFeed(FEED_URL, auth_token=None, auth_scheme="bearer")
    client = _client(feed)
    set_transient_5xx(2)
    body, _ = client.fetch()
    assert b"<listings" in body
    client.close()


def test_retries_exhausted_raises_api_error():
    feed = PropertyengineFeed(FEED_URL, auth_token=None, auth_scheme="bearer")
    client = _client(feed, max_retries=2)
    set_transient_5xx(5)
    with pytest.raises(PropertyEngineAPIError):
        client.fetch()
    client.close()


def test_unconfigured_feed_url_raises_auth_error():
    client = PropertyEngineClient(feed=None, transport=mock_transport())
    # resolve_propertyengine_feed() returns None with no env / .env.local
    with pytest.raises(PropertyEngineAuthError):
        client.fetch()
    client.close()


def test_repr_redacts_the_token(caplog):
    feed = PropertyengineFeed(FEED_URL, auth_token="super-secret", auth_scheme="bearer")
    client = _client(feed)
    with caplog.at_level(logging.DEBUG):
        text = repr(client)
    assert "super-secret" not in text
    assert "<bearer>" in text
    client.close()


def test_read_file_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("read_file must not hit the network")

    client = PropertyEngineClient(feed=None, transport=httpx.MockTransport(handler))
    body = client.read_file(FIXTURES / "feed.xml")
    assert b"<Property>" in body
    client.close()
