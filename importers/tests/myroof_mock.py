"""An httpx.MockTransport serving the bundled MyRoof fixture feed — no network.

``mock_transport()`` serves ``fixtures/feed.txt`` for any ``{base_url}/{token}``.
``set_body`` / ``set_status`` / ``set_transient_5xx`` override it for one test;
``seen_urls()`` returns every requested URL (to assert the token is in the path).
"""

from __future__ import annotations

from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/myroof/fixtures"

BASE_URL = "https://feed.example.test/myroof"

_DEFAULT = (FIXTURES / "feed.txt").read_bytes()

_state: dict[str, object] = {}


def reset() -> None:
    _state.clear()
    _state.update(
        body=_DEFAULT,
        content_type="text/plain; charset=utf-8",
        status=200,
        transient_5xx=0,
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


def seen_urls() -> list[str]:
    return _state["seen_urls"]  # type: ignore[return-value]


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _handler(request: httpx.Request) -> httpx.Response:
    _state["seen_urls"].append(str(request.url))  # type: ignore[union-attr]

    if _state["transient_5xx"]:
        _state["transient_5xx"] = int(_state["transient_5xx"]) - 1
        return httpx.Response(503, text="try again")

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
