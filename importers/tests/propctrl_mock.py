"""An httpx.MockTransport that serves the sanitised PropCtrl fixtures — no network."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propctrl/fixtures"

BASE_URL = "https://api.propctrl.com"
MAX_IDS = 10


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def load_listings() -> list[dict]:
    return _load("listings.json")  # type: ignore[return-value]


def load_changes() -> dict:
    return _load("changes.json")  # type: ignore[return-value]


_ENTITY = {
    "suburbs": ("suburbIds", "suburbId", "suburbs.json"),
    "agencies": ("agencyIds", "agencyId", "agencies.json"),
    "branches": ("branchIds", "branchId", "branches.json"),
    "agents": ("agentIds", "agentId", "agents.json"),
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    query = parse_qs(request.url.query.decode())

    if not request.headers.get("authorization", "").startswith("Basic "):
        return httpx.Response(401)

    if path == "/listing/v1/admin/echo-authenticated":
        return httpx.Response(200, json={"message": query.get("message", ["ok"])[0]})

    if path == "/listing/v1/listings/changes":
        return httpx.Response(200, json=load_changes())

    if path == "/listing/v1/listings":
        ids = {int(i) for i in query.get("listingIds", [])}
        if len(ids) > MAX_IDS:
            return httpx.Response(400, json={"errorMessage": "listingIds must be 10 items or less"})
        return httpx.Response(
            200, json=[x for x in load_listings() if x["listingId"] in ids]
        )

    for kind, (param, id_key, fixture) in _ENTITY.items():
        if path == f"/listing/v1/{kind}":
            ids = {int(i) for i in query.get(param, [])}
            if len(ids) > MAX_IDS:
                return httpx.Response(400, json={"errorMessage": "too many ids"})
            rows = [r for r in _load(fixture) if r[id_key] in ids]  # type: ignore[index]
            return httpx.Response(200, json=rows)

    return httpx.Response(404, json={"errorMessage": f"unmapped fixture path {path}"})


def mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(_handler)
