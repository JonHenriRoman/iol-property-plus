"""PropCtrl Listing Service v1 client — Basic auth, the changes cursor, batched
by-id fetches.

Contract discovered from the OpenAPI spec at
``<base>/v1-listing/swagger.json`` and verified against the live API:

- Auth is HTTP Basic on every request (``base64(username:password)``). There is
  no session token to renew.
- ``GET /listing/v1/listings/changes?fromDate=<ISO-8601>`` returns
  ``{ items: [...], nextFromDate }`` — a delta feed, not a paginated one.
  ``nextFromDate`` is the cursor for the following run.
- ``GET /listing/v1/listings?listingIds=…`` returns full ``Listing`` objects,
  **at most 10 ids per call**.
- ``suburbs`` / ``agencies`` / ``branches`` / ``agents`` are fetched the same way,
  by id, and are not subject to the 10-id cap.

The Basic credential is built once into a private attribute; ``__repr__`` and
every log line redact it.
"""

from __future__ import annotations

import base64
import json
import logging
import stat
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from iol_importers.config import (
    PROPCTRL_DIR,
    PropctrlCredentials,
    resolve_propctrl_credentials,
)

logger = logging.getLogger("iol_importers.propctrl")

MAX_LISTING_IDS = 10  # enforced by the API: 11 -> 400 "listingIds must be 10 items or less"

_CHANGES_PATH = "/listing/v1/listings/changes"
_LISTINGS_PATH = "/listing/v1/listings"
_ECHO_AUTH_PATH = "/listing/v1/admin/echo-authenticated"
_ENTITY_PATHS: dict[str, tuple[str, str]] = {
    # kind -> (path, query parameter name)
    "suburbs": ("/listing/v1/suburbs", "suburbIds"),
    "agencies": ("/listing/v1/agencies", "agencyIds"),
    "branches": ("/listing/v1/branches", "branchIds"),
    "agents": ("/listing/v1/agents", "agentIds"),
}
_ENTITY_ID_KEY: dict[str, str] = {
    "suburbs": "suburbId",
    "agencies": "agencyId",
    "branches": "branchId",
    "agents": "agentId",
}


class PropctrlAuthError(RuntimeError):
    """The credentials were rejected (HTTP 401) or are not configured."""


def _chunks(items: list[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class PropctrlClient:
    def __init__(
        self,
        *,
        credentials: PropctrlCredentials | None = None,
        transport: httpx.BaseTransport | None = None,
        state_dir: Any = None,
    ) -> None:
        self._credentials = credentials
        self._auth_header: str | None = None
        self._state_dir = state_dir if state_dir is not None else PROPCTRL_DIR
        self._http = httpx.Client(
            base_url=self._creds.base_url,
            timeout=120.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._cache: dict[str, dict[int, dict[str, Any]]] = {
            "suburbs": {},
            "agencies": {},
            "branches": {},
            "agents": {},
        }

    def __repr__(self) -> str:
        state = "<set>" if self._auth_header else None
        return f"PropctrlClient(base_url={self._creds.base_url!r}, auth={state})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PropctrlClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- auth -------------------------------------------------------------

    @property
    def _creds(self) -> PropctrlCredentials:
        if self._credentials is None:
            self._credentials = resolve_propctrl_credentials()
        if self._credentials is None:
            raise PropctrlAuthError(
                "PROPCTRL_API_USERNAME / PROPCTRL_API_PASSWORD are not set "
                "(process env or .env.local)."
            )
        return self._credentials

    def _headers(self) -> dict[str, str]:
        if self._auth_header is None:
            creds = self._creds
            raw = f"{creds.username}:{creds.password}".encode()
            self._auth_header = "Basic " + base64.b64encode(raw).decode()
        return {"Authorization": self._auth_header}

    def echo(self) -> bool:
        """Verify the credentials against ``/admin/echo-authenticated``."""
        resp = self._http.get(
            _ECHO_AUTH_PATH, params={"message": "ping"}, headers=self._headers()
        )
        if resp.status_code == httpx.codes.UNAUTHORIZED:
            raise PropctrlAuthError("PropCtrl rejected the credentials (HTTP 401)")
        resp.raise_for_status()
        return True

    # -- fetch ----------------------------------------------------------

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        resp = self._http.get(path, params=params, headers=self._headers())
        if resp.status_code == httpx.codes.UNAUTHORIZED:
            raise PropctrlAuthError("PropCtrl rejected the credentials (HTTP 401)")
        resp.raise_for_status()
        return resp.json()

    def fetch_changes(self, from_date: str) -> tuple[list[dict[str, Any]], str]:
        """Return ``(items, next_from_date)`` for everything changed since ``from_date``."""
        body = self._get(_CHANGES_PATH, params={"fromDate": from_date})
        items = body.get("items") or []
        next_from_date = body.get("nextFromDate") or from_date
        return items, next_from_date

    def iter_listings(self, listing_ids: Iterable[int]) -> Iterator[dict[str, Any]]:
        """Yield full ``Listing`` objects for ``listing_ids``, ten ids per request."""
        ids = list(dict.fromkeys(int(i) for i in listing_ids))
        for chunk in _chunks(ids, MAX_LISTING_IDS):
            yield from self._get(_LISTINGS_PATH, params={"listingIds": chunk}) or []

    def _get_entities(self, kind: str, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        cache = self._cache[kind]
        path, param = _ENTITY_PATHS[kind]
        id_key = _ENTITY_ID_KEY[kind]
        wanted = [int(i) for i in dict.fromkeys(ids) if int(i) not in cache]
        for chunk in _chunks(wanted, MAX_LISTING_IDS):
            for row in self._get(path, params={param: chunk}) or []:
                if row.get(id_key) is not None:
                    cache[int(row[id_key])] = row
        return {int(i): cache[int(i)] for i in ids if int(i) in cache}

    def get_suburbs(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        return self._get_entities("suburbs", ids)

    def get_agencies(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        return self._get_entities("agencies", ids)

    def get_branches(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        return self._get_entities("branches", ids)

    def get_agents(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        return self._get_entities("agents", ids)

    # -- checkpoint ---------------------------------------------------

    def _checkpoint_path(self) -> Any:
        return self._state_dir / "checkpoint.json"

    def load_checkpoint(self) -> str | None:
        path = self._checkpoint_path()
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text()).get("next_from_date") or None
        except (ValueError, OSError):
            return None

    def save_checkpoint(self, next_from_date: str) -> None:
        path = self._checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"next_from_date": next_from_date}))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
