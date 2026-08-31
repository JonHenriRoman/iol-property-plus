"""An httpx.MockTransport serving the sanitised Entegral fixtures + fake images.

No network. ``mock_transport()`` resets all overrides; the ``set_*`` helpers let a
test change what an office returns on its next call (for the reconcile / empty
/ mapping-failure cases).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/entegral/fixtures"
IMG = FIXTURES / "img"

_SAMPLE_JPG = (IMG / "sample.jpg").read_bytes()
_SAMPLE_PNG = (IMG / "sample.png").read_bytes()
_SECOND_PNG = (IMG / "second.png").read_bytes()
_NOT_IMAGE = (IMG / "notimage.txt").read_bytes()

# per-officeref override for the next officelistings call: ref -> list[dict]
_LISTING_OVERRIDES: dict[str, list[dict]] = {}
_OFFICES_OVERRIDE: list[dict] | None = None


def load_inner(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def offices() -> list[dict]:
    return load_inner("officeslist.json")["offices"]  # type: ignore[index]


def office_listings(ref: str) -> list[dict]:
    if ref in _LISTING_OVERRIDES:
        return _LISTING_OVERRIDES[ref]
    path = FIXTURES / f"officelistings_{ref}.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text())["listings"]


def set_office_listings(ref: str, listings: list[dict]) -> None:
    _LISTING_OVERRIDES[ref] = listings


def set_offices(rows: list[dict] | None) -> None:
    global _OFFICES_OVERRIDE
    _OFFICES_OVERRIDE = rows


def reset() -> None:
    _LISTING_OVERRIDES.clear()
    set_offices(None)


def _image_response(path: str) -> httpx.Response:
    if path.endswith("missing.jpg") or "/404/" in path:
        return httpx.Response(404, text="not found")
    if path.endswith(".txt") or path.endswith("notimage.jpg"):
        return httpx.Response(200, content=_NOT_IMAGE, headers={"content-type": "image/jpeg"})
    if path.endswith(".png"):
        body = _SECOND_PNG if "second" in path else _SAMPLE_PNG
        return httpx.Response(200, content=body, headers={"content-type": "image/png"})
    return httpx.Response(200, content=_SAMPLE_JPG, headers={"content-type": "image/jpeg"})


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    path = request.url.path

    if host in ("img.entegral.net", "tours.example.test"):
        return _image_response(path)

    if not request.headers.get("authorization", "").startswith("Basic "):
        return httpx.Response(401, json={"error": "unauthorised"})

    if path == "/api/officeslist":
        rows = _OFFICES_OVERRIDE if _OFFICES_OVERRIDE is not None else offices()
        return httpx.Response(200, json={"offices": rows})

    if path == "/api/listings":
        query = parse_qs(request.url.query.decode())
        ref = query.get("ref", [""])[0]
        return httpx.Response(200, json={"listings": office_listings(ref)})

    return httpx.Response(404, json={"error": f"unmapped {path}"})


def mock_transport() -> httpx.MockTransport:
    reset()
    return httpx.MockTransport(_handler)
