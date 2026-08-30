"""Propdata API client — login, token renewal, paginated listing fetch, id lookups.

The bearer token is held in a private attribute, redacted from ``repr()``, and
never written to a log or to a record's ``raw_data``. It is persisted (mode 0600)
to ``data/propdata/token-<site>.json`` so a run renews the previous session
instead of re-authenticating with Basic auth.
"""

from __future__ import annotations

import base64
import json
import logging
import stat
from collections.abc import Iterator
from typing import Any

import httpx

from iol_importers.config import PROPDATA_DIR, PropdataCredentials, resolve_propdata_credentials

logger = logging.getLogger("iol_importers.propdata")

API_BASE = "https://api-gw.propdata.net"
RENEW_URL = f"{API_BASE}/users/api/v1/renew-token/"
LISTINGS_URL = f"{API_BASE}/listings/api/v1/{{category}}/"
LOCATION_URL = f"{API_BASE}/locations/api/v1/locations/{{id}}/"
BRANCH_URL = f"{API_BASE}/branches/api/v1/branches/{{id}}/"
AGENT_URL = f"{API_BASE}/users/api/v1/agents/{{id}}/"

_PAGE_SIZE = 100


class PropdataAuthError(RuntimeError):
    """Login or token renewal failed."""


class PropdataClient:
    def __init__(
        self,
        site_domain: str,
        *,
        credentials: PropdataCredentials | None = None,
        transport: httpx.BaseTransport | None = None,
        token_dir: Any = None,
    ) -> None:
        self.site_domain = site_domain
        self._credentials = credentials
        self._token: str | None = None
        self._http = httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._token_dir = token_dir if token_dir is not None else PROPDATA_DIR
        self._cache: dict[str, dict[int, dict[str, Any]]] = {
            "location": {},
            "branch": {},
            "agent": {},
        }

    def __repr__(self) -> str:
        state = "<set>" if self._token else None
        return f"PropdataClient(site_domain={self.site_domain!r}, token={state})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PropdataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- auth ---------------------------------------------------------------

    @property
    def _creds(self) -> PropdataCredentials:
        if self._credentials is None:
            self._credentials = resolve_propdata_credentials()
        if self._credentials is None:
            raise PropdataAuthError(
                "PROP_DATA_API_USERNAME / PROP_DATA_API_PASSWORD are not set "
                "(process env or .env.local)."
            )
        return self._credentials

    def authenticate(self) -> None:
        """HTTP Basic login. Picks the token for ``site_domain`` from ``clients[]``."""
        creds = self._creds
        basic = base64.b64encode(f"{creds.username}:{creds.password}".encode()).decode()
        resp = self._http.get(creds.login_url, headers={"Authorization": f"Basic {basic}"})
        if resp.status_code != httpx.codes.OK:
            raise PropdataAuthError(f"login failed: HTTP {resp.status_code}")
        clients = resp.json().get("clients", [])
        for client in clients:
            if client.get("site", {}).get("domain") == self.site_domain:
                self._token = client["token"]
                logger.info("propdata: authenticated for site %s", self.site_domain)
                self._persist_token()
                return
        available = sorted(c.get("site", {}).get("domain", "?") for c in clients)
        raise PropdataAuthError(
            f"login succeeded but no client for site {self.site_domain!r}; "
            f"available: {available}"
        )

    def renew(self) -> None:
        """Extend the session. The new token is in the ``token`` response header."""
        if not self._token:
            raise PropdataAuthError("renew() called with no token")
        resp = self._http.get(RENEW_URL, headers={"Authorization": f"Bearer {self._token}"})
        if resp.status_code != httpx.codes.OK:
            raise PropdataAuthError(f"token renewal failed: HTTP {resp.status_code}")
        new_token = resp.headers.get("token")
        if not new_token:
            raise PropdataAuthError("token renewal response had no 'token' header")
        self._token = new_token
        logger.info("propdata: token renewed for site %s", self.site_domain)
        self._persist_token()

    def ensure_token(self) -> None:
        """Renew the persisted token; fall back to Basic login."""
        stored = self._load_token()
        if stored:
            self._token = stored
            try:
                self.renew()
                return
            except (PropdataAuthError, httpx.HTTPError) as exc:
                logger.warning("propdata: renew failed (%s); re-authenticating", exc)
                self._token = None
        self.authenticate()

    def _token_path(self) -> Any:
        return self._token_dir / f"token-{self.site_domain}.json"

    def _persist_token(self) -> None:
        path = self._token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"site": self.site_domain, "token": self._token}))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def _load_token(self) -> str | None:
        path = self._token_path()
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text()).get("token") or None
        except (ValueError, OSError):
            return None

    # -- fetch ------------------------------------------------------------

    def _get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        if not self._token:
            raise PropdataAuthError("no token; call ensure_token() first")
        resp = self._http.get(
            url, params=params, headers={"Authorization": f"Bearer {self._token}"}
        )
        resp.raise_for_status()
        return resp.json()

    def iter_listings(
        self, category: str, *, page_limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every ``results`` item for a category, following ``next`` to the end."""
        url: str | None = LISTINGS_URL.format(category=category)
        params: dict[str, Any] | None = {"status": "Active", "limit": _PAGE_SIZE}
        pages = 0
        while url is not None:
            body = self._get(url, params=params)
            yield from body.get("results", [])
            pages += 1
            if page_limit is not None and pages >= page_limit:
                return
            url = body.get("next")  # absolute URL with its own limit/offset
            params = None

    def _lookup(self, kind: str, template: str, id_: int) -> dict[str, Any]:
        cache = self._cache[kind]
        if id_ not in cache:
            try:
                cache[id_] = self._get(template.format(id=id_))
            except httpx.HTTPStatusError:
                cache[id_] = {}
        return cache[id_]

    def get_location(self, id_: int) -> dict[str, Any]:
        return self._lookup("location", LOCATION_URL, id_)

    def get_branch(self, id_: int) -> dict[str, Any]:
        return self._lookup("branch", BRANCH_URL, id_)

    def get_agent(self, id_: int) -> dict[str, Any]:
        return self._lookup("agent", AGENT_URL, id_)
