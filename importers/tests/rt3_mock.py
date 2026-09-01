"""An httpx.MockTransport serving the bundled RT3 province fixtures — no network.

``mock_transport()`` serves ``fixtures/iol-{Province}.txt`` by URL.
``set_body`` / ``set_status`` / ``set_transient_5xx`` / ``set_transient_429``
override the response for every province; ``set_province_error(province, status)``
fails just one province. ``seen_urls()`` returns every requested URL.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/rt3/fixtures"

BASE_URL = "https://feed.example.test"

_PROVINCE_URL = re.compile(r"/iol-([^/]+)\.txt$")

_state: dict[str, object] = {}


def reset() -> None:
    _state.clear()
    _state.update(
        body=None,
        content_type="text/plain; charset=utf-8",
        status=200,
        transient_5xx=0,
        transient_429=0,
        province_errors={},
        seen_urls=[],
    )


reset()


def set_body(body: bytes, *, content_type: str = "text/plain; charset=utf-8") -> None:
    _state["body"] = body
    _state["content_type"] = content_type


def set_status(status: int) -> None:
    _state["status"] = status


def set_transient_5xx(count: int) -> None:
    _state["transient_5xx"] = count


def set_transient_429(count: int) -> None:
    _state["transient_429"] = count


def set_province_error(province: str, status: int = 500) -> None:
    _state["province_errors"][province] = status  # type: ignore[index]


def seen_urls() -> list[str]:
    return _state["seen_urls"]  # type: ignore[return-value]


def _fixture_for(province: str) -> bytes:
    return (FIXTURES / f"iol-{province}.txt").read_bytes()


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    _state["seen_urls"].append(url)  # type: ignore[union-attr]

    m = _PROVINCE_URL.search(url)
    province = m.group(1) if m else ""

    if province in _state["province_errors"]:  # type: ignore[operator]
        return httpx.Response(int(_state["province_errors"][province]), text="province error")
    if _state["transient_5xx"]:
        _state["transient_5xx"] = int(_state["transient_5xx"]) - 1
        return httpx.Response(503, text="try again")
    if _state["transient_429"]:
        _state["transient_429"] = int(_state["transient_429"]) - 1
        return httpx.Response(429, text="slow down")

    status = int(_state["status"])
    if status != 200:
        return httpx.Response(status, text="error")

    body = _state["body"]
    if body is None:
        body = _fixture_for(province) if province else b""
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": str(_state["content_type"])},
    )


def mock_transport() -> httpx.MockTransport:
    reset()
    return httpx.MockTransport(_handler)
