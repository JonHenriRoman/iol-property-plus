"""Webbox feed client — one HTTP GET for a site's whole book, or a file off disk.

The URL embeds ``siteid`` + ``securitykey`` in its path — the URL itself is the
credential. Neither value is ever put in ``__repr__``, a log line, or an
exception message: a bad key surfaces as a plain HTTP status.

A response that is not 2xx, or whose body does not contain ``<property`` near the
top (an HTML error page, an empty body), raises :class:`WebboxAPIError` rather
than being handed to the parser — so a broken fetch cannot make the downstream
``withdraw_missing`` reconcile the whole book to zero.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from iol_importers.config import resolve_webbox_feed_template

logger = logging.getLogger("iol_importers.webbox")

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_SNIFF_BYTES = 4096


class WebboxAPIError(RuntimeError):
    """The feed host returned an error, a non-feed body, or retries were exhausted."""


def _looks_like_feed(body: bytes) -> bool:
    return b"<property" in body[:_SNIFF_BYTES].lower()


class WebboxClient:
    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._template = resolve_webbox_feed_template()
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._http = httpx.Client(
            timeout=180.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/xml, text/xml, */*;q=0.1"},
        )

    def __repr__(self) -> str:
        return f"WebboxClient(base_url={self._base_url!r})"  # never the key

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WebboxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_file(self, path: str | Path) -> bytes:
        """Read a local feed file. No network."""
        return Path(path).read_bytes()

    def fetch(self, siteid: str, securitykey: str) -> bytes:
        """GET the site feed. Returns the raw XML body.

        The securitykey is not echoed into any error text — a bad key surfaces as
        a plain ``HTTP 403``/``404`` (or a non-feed body).
        """
        url = self._base_url + self._template.format(siteid=siteid, securitykey=securitykey)
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._http.get(url)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code in _RETRY_STATUS:
                    last_error = WebboxAPIError(f"feed: HTTP {resp.status_code}")
                elif resp.status_code >= 400:
                    raise WebboxAPIError(
                        f"feed: HTTP {resp.status_code} — check the siteid / securitykey"
                    )
                elif not _looks_like_feed(resp.content):
                    raise WebboxAPIError(
                        "feed body is not Webbox XML (no <property> near the top; "
                        f"HTTP {resp.status_code}, "
                        f"content-type {resp.headers.get('content-type', '')!r})"
                    )
                else:
                    return resp.content
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise WebboxAPIError(f"feed: retries exhausted ({last_error})")
