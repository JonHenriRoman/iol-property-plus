"""Offline unit tests — EntegralClient against the mock transport."""

from __future__ import annotations

import logging

import httpx
import pytest

from entegral_mock import mock_transport, set_office_listings
from iol_importers.config import EntegralCredentials
from iol_importers.entegral.client import (
    EntegralAPIError,
    EntegralAuthError,
    EntegralClient,
    office_name,
    office_reference,
)

CREDS = EntegralCredentials(
    username="sandbox-user",
    password="do-not-log-this-secret",
    base_url="https://sync.entegral.net/api",
)


def _client(transport=None, **kw) -> EntegralClient:
    return EntegralClient(
        credentials=CREDS,
        transport=transport if transport is not None else mock_transport(),
        retry_base_delay=0.0,
        **kw,
    )


def test_list_offices_parses_wrapper():
    with _client() as client:
        offices = client.list_offices()
    assert [office_reference(o) for o in offices] == ["OFF001", "OFF002"]
    assert office_name(offices[0]) == "Demo Property Group Claremont"


def test_office_listings_is_called_per_ref():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/listings":
            seen.append(dict(request.url.params)["ref"])
            return httpx.Response(200, json={"listings": []})
        return httpx.Response(200, json={"offices": []})

    client = EntegralClient(
        credentials=CREDS, transport=httpx.MockTransport(handler), retry_base_delay=0.0
    )
    with client:
        client.office_listings("OFF001")
        client.office_listings("OFF002")
    assert seen == ["OFF001", "OFF002"]


def test_basic_auth_header_on_every_request():
    headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"offices": [], "listings": []})

    client = EntegralClient(
        credentials=CREDS, transport=httpx.MockTransport(handler), retry_base_delay=0.0
    )
    with client:
        client.list_offices()
        client.office_listings("OFF001")
    assert headers and all(h.startswith("Basic ") for h in headers)


def test_401_raises_auth_error():
    client = EntegralClient(
        credentials=EntegralCredentials("u", "p", "https://sync.entegral.net/api"),
        transport=httpx.MockTransport(lambda r: httpx.Response(401)),
        retry_base_delay=0.0,
    )
    with client, pytest.raises(EntegralAuthError):
        client.list_offices()


def test_transient_503_is_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"offices": []})

    client = EntegralClient(
        credentials=CREDS, transport=httpx.MockTransport(handler), retry_base_delay=0.0
    )
    with client:
        assert client.list_offices() == []
    assert calls["n"] == 3


def test_retries_exhausted_raises():
    client = EntegralClient(
        credentials=CREDS,
        transport=httpx.MockTransport(lambda r: httpx.Response(502)),
        retry_base_delay=0.0,
        max_retries=2,
    )
    with client, pytest.raises(EntegralAPIError):
        client.list_offices()


def test_credentials_never_in_repr_or_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="iol_importers.entegral")
    with _client() as client:
        client.list_offices()
        text = repr(client)
    assert "do-not-log-this-secret" not in text
    assert "do-not-log-this-secret" not in caplog.text
    assert "auth=<set>" in text


def test_set_office_listings_override():
    transport = mock_transport()
    set_office_listings("OFF001", [{"clientPropertyID": "X-1"}])
    with _client(transport) as client:
        rows = client.office_listings("OFF001")
    assert [r["clientPropertyID"] for r in rows] == ["X-1"]
