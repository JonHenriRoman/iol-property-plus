"""AllSA feed client — one HTTP GET for an agency's whole book, or a file off disk.

The endpoint is ``{base_url}?agencyid={agency_id}`` — unauthenticated, ~3.5 MB of
XML for a mid-size agency. Quirks handled here:

* a missing/blank ``agencyid`` returns **HTTP 200 with an ASP.NET "Runtime Error"
  HTML page**, not an error status — caught by the body sniff below;
* a bogus ``agencyid`` returns HTTP 200 with ``<Listings />`` — that is a valid
  empty feed and is left for :mod:`.parse` / the adapter to treat as "withdraw
  nothing", not an error;
* transient 5xx / transport errors are retried with exponential backoff.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from iol_importers.config import resolve_allsa_base_url

logger = logging.getLogger("iol_importers.allsa")

_RETRY_STATUS = frozenset({500, 502, 503, 504})
_XML_PREFIXES = (b"<?xml", b"<listings")


class AllsaAPIError(RuntimeError):
    """The feed host returned an error, an HTML body, or retries were exhausted."""


def _looks_like_xml(body: bytes) -> bool:
    head = body.lstrip().lstrip(b"\xef\xbb\xbf").lstrip()[:64].lower()
    return head.startswith(_XML_PREFIXES)


class AllsaClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._base_url = (base_url or resolve_allsa_base_url()).strip()
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._http = httpx.Client(
            timeout=180.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/xml, text/xml, */*;q=0.1"},
        )

    def __repr__(self) -> str:
        return f"AllsaClient(base_url={self._base_url!r})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AllsaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_file(self, path: str | Path) -> bytes:
        """Read a local feed file. No network."""
        return Path(path).read_bytes()

    def fetch(self, agency_id: str) -> bytes:
        """GET ``{base_url}?agencyid={agency_id}``. Returns the raw XML body."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._http.get(self._base_url, params={"agencyid": agency_id})
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code in _RETRY_STATUS:
                    last_error = AllsaAPIError(f"feed: HTTP {resp.status_code}")
                elif resp.status_code >= 400:
                    raise AllsaAPIError(
                        f"feed: HTTP {resp.status_code} for agencyid={agency_id} "
                        f"{resp.text[:200]!r}"
                    )
                else:
                    body = resp.content
                    content_type = resp.headers.get("content-type", "")
                    if "html" in content_type.lower() or not _looks_like_xml(body):
                        raise AllsaAPIError(
                            f"feed returned a non-XML body for agencyid={agency_id} "
                            f"(content-type {content_type!r}) — the endpoint serves an "
                            "ASP.NET error page when agencyid is missing or invalid."
                        )
                    return body
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise AllsaAPIError(f"feed: retries exhausted for agencyid={agency_id} ({last_error})")
