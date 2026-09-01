"""An httpx.MockTransport serving the bundled PropertyPost fixture feed — no network.

``mock_transport()`` serves ``fixtures/feed.txt`` for any URL.
``set_body`` / ``set_status`` / ``set_transient_5xx`` override it for one test;
``seen_urls()`` returns every requested URL.
"""

from __future__ import annotations

from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertypost/fixtures"

FEED_URL = "http://feed.example.test/DemoAgency.txt"

_DEFAULT = (FIXTURES / "feed.txt").read_bytes()

_state: dict[str, object] = {}


def reset() -> None:
    _state.clear()
    _state.update(
        body=_DEFAULT,
        content_type="text/plain; charset=utf-8",
        status=200,
        transient_5xx=0,
        transient_429=0,
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


def seen_urls() -> list[str]:
    return _state["seen_urls"]  # type: ignore[return-value]


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _handler(request: httpx.Request) -> httpx.Response:
    _state["seen_urls"].append(str(request.url))  # type: ignore[union-attr]

    if _state["transient_5xx"]:
        _state["transient_5xx"] = int(_state["transient_5xx"]) - 1
        return httpx.Response(503, text="try again")
    if _state["transient_429"]:
        _state["transient_429"] = int(_state["transient_429"]) - 1
        return httpx.Response(429, text="slow down")

    status = int(_state["status"])
    if status != 200:
        return httpx.Response(status, text="error")

    return httpx.Response(
        200,
        content=_state["body"],
        headers={"content-type": str(_state["content_type"])},
    )


def mock_transport() -> httpx.MockTransport:
    reset()
    return httpx.MockTransport(_handler)
