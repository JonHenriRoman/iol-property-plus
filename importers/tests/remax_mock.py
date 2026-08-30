"""An httpx.MockTransport that serves the sanitised RE/MAX fixtures — no network.

Fixtures keep the real double-encoded envelope (`{"Success": true, "data": "<json
string>"}`), so the client's decode path is exercised. The `_fail_once` set lets
a test make one endpoint return 504 before succeeding.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/remax/fixtures"

_FAIL_ONCE: set[str] = set()


def arm_transient_failure(endpoint: str) -> None:
    _FAIL_ONCE.add(endpoint)


def reset() -> None:
    _FAIL_ONCE.clear()


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def load_inner(name: str) -> dict:
    return json.loads(_load(name)["data"])


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers.get("x-api-key"), "x-api-key header missing"
    assert request.headers.get("authorization", "").startswith("AWS4-HMAC-SHA256 ")
    assert request.headers.get("x-amz-date")
    assert request.headers.get("x-amz-content-sha256")

    endpoint = request.url.path.rsplit("/", 1)[-1]
    body = json.loads(request.content or b"{}")

    if endpoint in _FAIL_ONCE:
        _FAIL_ONCE.discard(endpoint)
        return httpx.Response(504, json={"message": "Endpoint request timed out"})

    if endpoint == "lists":
        if body.get("agents"):
            return httpx.Response(200, json=_load("lists_agents.json"))
        if body.get("offices"):
            return httpx.Response(200, json=_load("lists_offices.json"))
        return httpx.Response(500, json={"Success": False, "Reason": "broken"})

    if endpoint == "lists-pagenate":
        page = str(body.get("page", "0"))
        return httpx.Response(200, json=_load(f"lists_pagenate_p{page}.json"))

    if endpoint == "lists_deleted":
        page = str(body.get("page", "0"))
        return httpx.Response(200, json=_load(f"lists_deleted_p{page}.json"))

    if endpoint == "agents-page":
        if str(body.get("page", "0")) != "0":
            return httpx.Response(
                200,
                json={
                    "Success": True,
                    "data": json.dumps(
                        {
                            "agent_details": {},
                            "branches": {"branch_details": []},
                            "properties": {"hasNextPage": False, "property": []},
                        }
                    ),
                },
            )
        return httpx.Response(200, json=_load("agents_page.json"))

    if endpoint == "listing":
        listings = _load("listings.json")
        key = str(body.get("listing_id"))
        if key in listings:
            return httpx.Response(200, json=listings[key])
        # any other id (the lists-pagenate p1 ids) -> a minimal but valid full shape,
        # so the incremental path can hydrate and import every changed listing.
        stub = {
            "property_id": int(key),
            "listing_type": "For Sale",
            "property_type": "House",
            "heading": {"_cdata": f"Stub listing {key}"},
            "price": {"amount": 500000, "periodicity": "", "poa": False},
            "date_last_updated": "2026-08-29T00:00:00.000Z",
            "published_datetime": None,
            "features": {},
            "photos": {"photo": []},
            "location": {"suburb": {"_cdata": "Testville"}},
            "agents": {"agent_details": []},
            "office": {},
        }
        return httpx.Response(200, json={"Success": True, "data": json.dumps({"property": [stub]})})

    return httpx.Response(404, json={"Success": False, "Reason": f"unmapped {endpoint}"})


def mock_transport() -> httpx.MockTransport:
    reset()
    return httpx.MockTransport(_handler)
