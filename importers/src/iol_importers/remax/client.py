"""RE/MAX feed client — SigV4-signed POSTs, the double-encoded envelope, retries,
and the pagination helpers for each sync path.

Contract (verified against the live API — it differs from *Feed Documentation
V1.6* in several places, see ``MAPPING_NOTES.md``):

- Every endpoint is ``POST`` with a JSON body, signed AWS SigV4 (`execute-api`,
  `eu-west-1`) **and** carrying an ``x-api-key`` header. The body also repeats the
  key as ``token`` (per the doc).
- Every response is ``{"Success": true, "data": "<JSON string>"}`` — ``data`` is a
  string that must be decoded a second time.
- API Gateway's 30 s ceiling trips on Lambda cold starts (``504``); a retry
  succeeds. ``/lists {listings:true}`` is genuinely broken (``500``) — the adapter
  uses ``/lists-pagenate`` instead.

Credentials live in a private attribute; ``__repr__`` and every log line redact
the secret key and the API key.
"""

from __future__ import annotations

import json
import logging
import stat
import time
from collections.abc import Iterator
from typing import Any

import httpx

from iol_importers.config import REMAX_DIR, RemaxCredentials, resolve_remax_credentials

from .signing import sign_headers

logger = logging.getLogger("iol_importers.remax")

_RETRY_STATUS = frozenset({500, 502, 503, 504})
_LISTS = "lists"
_LISTS_PAGENATE = "lists-pagenate"
_LISTS_DELETED = "lists_deleted"
_AGENTS_PAGE = "agents-page"
_LISTING = "listing"


class RemaxAPIError(RuntimeError):
    """A RE/MAX endpoint returned an error, a non-Success body, or exhausted retries."""


class RemaxCredentialsError(RemaxAPIError):
    """REMAX_ACCESS_KEY / REMAX_SECRET_KEY / REMAX_API_KEY are not configured."""


def _decode_envelope(payload: Any) -> Any:
    """Unwrap ``{"Success": …, "data": "<json string>"}`` (or ``{"body": …}``)."""
    if isinstance(payload, dict):
        if payload.get("Success") is False or payload.get("success") is False:
            raise RemaxAPIError(f"RE/MAX returned Success=false: {payload.get('Reason')!r}")
        inner = payload.get("data")
        if inner is None:
            body = payload.get("body")
            inner = body.get("data") if isinstance(body, dict) else body
        if inner is None:
            return payload
        return json.loads(inner) if isinstance(inner, str) else inner
    return payload


def _as_int_pages(meta: dict[str, Any]) -> bool:
    """``hasNextPage`` as sent by RE/MAX (bool, or absent)."""
    return bool(meta.get("hasNextPage"))


class RemaxClient:
    def __init__(
        self,
        *,
        credentials: RemaxCredentials | None = None,
        transport: httpx.BaseTransport | None = None,
        state_dir: Any = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._credentials = credentials
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._state_dir = state_dir if state_dir is not None else REMAX_DIR
        self._http = httpx.Client(
            timeout=120.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def __repr__(self) -> str:
        try:
            access = self._creds.access_key
            head = f"access_key={access[:4]}…" if access else "access_key=None"
        except RemaxAPIError:
            head = "access_key=None"
        return f"RemaxClient({head}, creds=<set>)"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> RemaxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- auth -----------------------------------------------------------

    @property
    def _creds(self) -> RemaxCredentials:
        if self._credentials is None:
            self._credentials = resolve_remax_credentials()
        if self._credentials is None:
            raise RemaxCredentialsError(
                "REMAX_ACCESS_KEY / REMAX_SECRET_KEY / REMAX_API_KEY are not set "
                "(process env or .env.local)."
            )
        return self._credentials

    # -- transport ----------------------------------------------------

    def _post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        creds = self._creds
        url = f"{creds.base_url}/{endpoint}"
        body = json.dumps({"token": creds.api_key, **payload}).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            headers = {
                "Content-Type": "application/json",
                "x-api-key": creds.api_key,
                **sign_headers(
                    method="POST",
                    url=url,
                    body=body,
                    access_key=creds.access_key,
                    secret_key=creds.secret_key,
                ),
            }
            try:
                resp = self._http.post(url, content=body, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code not in _RETRY_STATUS:
                    if resp.status_code >= 400:
                        raise RemaxAPIError(
                            f"{endpoint}: HTTP {resp.status_code} {resp.text[:200]!r}"
                        )
                    return _decode_envelope(resp.json())
                last_error = RemaxAPIError(f"{endpoint}: HTTP {resp.status_code}")
                logger.warning(
                    "remax: %s HTTP %s (attempt %d/%d)",
                    endpoint,
                    resp.status_code,
                    attempt + 1,
                    self._max_retries,
                )
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise RemaxAPIError(f"{endpoint}: retries exhausted ({last_error})")

    # -- sync paths -------------------------------------------------

    def list_agent_ids(self) -> list[int]:
        """``/lists {agents:true}`` — every agent id for the token, de-duplicated."""
        data = self._post(_LISTS, {"listings": False, "offices": False, "agents": True})
        seen: dict[int, None] = {}
        for row in data.get("agent", []):
            aid = row.get("agent_id")
            if isinstance(aid, int):
                seen.setdefault(aid, None)
        return list(seen)

    def list_office_ids(self) -> list[int]:
        """``/lists {offices:true}`` — every office id for the token."""
        data = self._post(_LISTS, {"listings": False, "offices": True, "agents": False})
        return [row["id"] for row in data.get("office", []) if isinstance(row.get("id"), int)]

    def iter_agent_properties(
        self, agent_id: int, *, max_pages: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """``/agents-page`` — full property objects for an agent, following pages.

        Yields ``(property, agent_details, branch_details)`` folded into each
        property as ``_remax_agent`` / ``_remax_branch`` so the mapper has them.
        """
        page = 0
        while True:
            data = self._post(_AGENTS_PAGE, {"agent_id": str(agent_id), "page": str(page)})
            agent = data.get("agent_details") or {}
            branches = (data.get("branches") or {}).get("branch_details") or []
            branch = branches[0] if branches else {}
            props = data.get("properties") or {}
            for prop in props.get("property", []):
                prop["_remax_agent"] = agent
                prop["_remax_branch"] = branch
                yield prop
            page += 1
            if not _as_int_pages(props):
                return
            if max_pages is not None and page >= max_pages:
                return

    def iter_changed_listings(
        self, start_date: str | None, *, max_pages: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """``/lists-pagenate {listings:true}`` — the thin change list, following pages."""
        page = 0
        while True:
            payload: dict[str, Any] = {
                "listings": True,
                "offices": False,
                "agents": False,
                "page": str(page),
            }
            if start_date:
                payload["start_date"] = start_date
            data = self._post(_LISTS_PAGENATE, payload)
            yield from data.get("listing", [])
            page += 1
            if not _as_int_pages(data):
                return
            if max_pages is not None and page >= max_pages:
                return

    def get_listing(self, listing_id: int | str) -> dict[str, Any] | None:
        """``/listing {listing_id}`` — the full single-listing shape."""
        data = self._post(_LISTING, {"listing_id": str(listing_id)})
        props = data.get("property") or []
        return props[0] if props else None

    def iter_deleted_listings(self, *, max_pages: int | None = None) -> Iterator[dict[str, Any]]:
        """``/lists_deleted {listings:true}`` — following pages (it *is* paginated)."""
        page = 0
        while True:
            data = self._post(
                _LISTS_DELETED, {"listings": True, "agents": False, "page": str(page)}
            )
            yield from data.get("listing", [])
            page += 1
            if not _as_int_pages(data):
                return
            if max_pages is not None and page >= max_pages:
                return

    # -- checkpoint -------------------------------------------------

    def _checkpoint_path(self) -> Any:
        return self._state_dir / "checkpoint.json"

    def load_checkpoint(self) -> str | None:
        path = self._checkpoint_path()
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text()).get("start_date") or None
        except (ValueError, OSError):
            return None

    def save_checkpoint(self, start_date: str) -> None:
        path = self._checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"start_date": start_date}))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
