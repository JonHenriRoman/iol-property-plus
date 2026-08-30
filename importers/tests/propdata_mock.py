"""An httpx.MockTransport that serves the recorded Propdata fixtures — no network."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propdata/fixtures"

API_HOST = "https://api-gw.propdata.net"
_NEW_TOKEN = "renewed.jwt.token-value"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    query = parse_qs(request.url.query.decode())

    if path.endswith("/users/public-api/login/"):
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json=_load("login.json"))

    if path.endswith("/users/api/v1/renew-token/"):
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(200, headers={"token": _NEW_TOKEN}, json=_load("renew.json")["body"])

    for category in ("residential", "commercial", "holiday", "projects"):
        if path.endswith(f"/listings/api/v1/{category}/"):
            offset = int(query.get("offset", ["0"])[0])
            if offset == 0:
                page = _load(f"{category}_page1.json")
                # residential has a real page 2 fixture; point next at it and
                # let the others end after page 1.
                page["next"] = (
                    f"{API_HOST}/listings/api/v1/residential/?limit=3&offset=3"
                    if category == "residential"
                    else None
                )
            elif category == "residential":
                page = _load("residential_page2.json")
                page["next"] = None
            else:
                page = {"count": 0, "next": None, "previous": None, "results": []}
            return httpx.Response(200, json=page)

    for kind, fixture in (("locations", "locations.json"), ("branches", "branches.json")):
        if f"/{kind}/api/v1/" in path:
            id_ = path.rstrip("/").rsplit("/", 1)[-1]
            data = _load(fixture)
            return httpx.Response(200 if id_ in data else 404, json=data.get(id_, {}))
    if "/users/api/v1/agents/" in path:
        id_ = path.rstrip("/").rsplit("/", 1)[-1]
        data = _load("agents.json")
        return httpx.Response(200 if id_ in data else 404, json=data.get(id_, {}))

    return httpx.Response(404, json={"detail": f"unmapped fixture path {path}"})


def mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(_handler)


RENEWED_TOKEN = _NEW_TOKEN
