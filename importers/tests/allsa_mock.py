"""An httpx.MockTransport serving the bundled AllSA fixture feed — no network.

``mock_transport()`` serves ``fixtures/feed.xml`` for any ``agencyid``.
``set_body(...)`` / ``set_status(...)`` / ``set_transient_5xx(...)`` override it
for one test; ``reset()`` restores the default.
"""

from __future__ import annotations

from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/allsa/fixtures"

BASE_URL = "https://feed.example.test/allsa/iol.ashx"

_DEFAULT = (FIXTURES / "feed.xml").read_bytes()

_state: dict[str, object] = {}


def reset() -> None:
    _state.clear()
    _state.update(
        body=_DEFAULT,
        content_type="text/xml; charset=utf-8",
        status=200,
        transient_5xx=0,
        seen_params=[],
        seen_headers=[],
    )


reset()


def set_body(body: bytes, *, content_type: str = "text/xml; charset=utf-8") -> None:
    _state["body"] = body
    _state["content_type"] = content_type


def set_status(status: int) -> None:
    _state["status"] = status


def set_transient_5xx(count: int) -> None:
    _state["transient_5xx"] = count


def seen_params() -> list[dict[str, str]]:
    return _state["seen_params"]  # type: ignore[return-value]


def seen_headers() -> list[httpx.Headers]:
    return _state["seen_headers"]  # type: ignore[return-value]


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _handler(request: httpx.Request) -> httpx.Response:
    _state["seen_params"].append(dict(request.url.params))  # type: ignore[union-attr]
    _state["seen_headers"].append(request.headers)  # type: ignore[union-attr]

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
