"""Download the Property24 canonical suburb CSV to a timestamped file.

This is the ONLY module in the package that performs network I/O. No test imports
it, so the test suite never reaches the live endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

# Public, unauthenticated GET endpoint — no API key, no auth header.
FEED_URL = "https://www.property24.com/general/getsuburbscsv"


def download(dest_dir: Path, *, timeout: float = 120.0) -> Path:
    """Fetch the feed and save it verbatim. Returns the saved file path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"suburbs-{stamp}.csv"

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(FEED_URL)
        response.raise_for_status()
        dest.write_bytes(response.content)

    return dest
