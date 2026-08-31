"""An httpx.MockTransport that serves the bundled PropertyEngine feed file — no network.

The feed is one file at one URL. ``mock_transport()`` serves ``fixtures/feed.xml``
by default; ``set_body(...)`` / ``set_status(...)`` override it for a single test,
and ``reset()`` restores the default. Requests without the expected
``Authorization`` header get 401 only when ``require_auth`` is on.
"""

from __future__ import annotations

from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertyengine/fixtures"

FEED_URL = "https://feed.example.test/propertyengine/listings"

_DEFAULT_XML = (FIXTURES / "feed.xml").read_bytes()
_DEFAULT_JSON = (FIXTURES / "feed.json").read_bytes()

_state: dict[str, object] = {}


def reset() -> None:
    _state.clear()
    _state.update(
        body=_DEFAULT_XML,
        content_type="application/xml",
        status=200,
        require_auth=False,
        transient_5xx=0,
    )


reset()


def set_body(body: bytes, *, content_type: str = "application/xml") -> None:
    _state["body"] = body
    _state["content_type"] = content_type


def use_json_fixture() -> None:
    set_body(_DEFAULT_JSON, content_type="application/json")


def use_xml_fixture() -> None:
    set_body(_DEFAULT_XML, content_type="application/xml")


def set_status(status: int) -> None:
    _state["status"] = status


def require_auth(value: bool = True) -> None:
    _state["require_auth"] = value


def set_transient_5xx(count: int) -> None:
    """Serve ``count`` 503s before the first success — exercises the retry path."""
    _state["transient_5xx"] = count


def _handler(request: httpx.Request) -> httpx.Response:
    if _state["require_auth"] and not request.headers.get("authorization"):
        return httpx.Response(401, text="unauthorized")

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
