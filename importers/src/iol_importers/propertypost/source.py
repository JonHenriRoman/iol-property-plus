"""Resolve one PropertyPost agency's feed URL from its ``feed_sources`` row.

PropertyPost publishes one static per-agency URL — a plain HTTP GET with no auth
header, no query token, no credential of any kind. The per-agency value is the
URL itself (its filename identifies the agency), so it lives in ``base_url``:

    INSERT INTO feed_sources (code, name, vendor_name, base_url)
    VALUES ('propertypost-bst', 'BST Properties (PropertyPost)', 'PropertyPost',
            'http://lms.propertypost.co.za/BstProperties.txt');

``auth_config`` is not used — there is nothing to hide.
``PROPERTYPOST_FEED_BASE_URL`` only supplies a default host for a row whose
``base_url`` is a bare host with no ``/<file>.txt`` path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url, resolve_propertypost_base_url


class PropertypostConfigError(RuntimeError):
    """The feed_sources row is missing or its base_url has no per-agency file path."""


@dataclass(frozen=True, slots=True)
class PropertypostSource:
    feed_source_code: str
    feed_url: str


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _has_file_path(url: str) -> bool:
    path = urlsplit(url).path.strip("/")
    return bool(path)


def resolve_source(
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
) -> PropertypostSource:
    """Read the agency feed URL off the ``feed_sources`` row. Read-only.

    Raises :class:`PropertypostConfigError` when the row is absent or its
    ``base_url`` carries no ``/<file>`` path — the whole point of the row is the
    per-agency file.
    """
    conn = (connect or _default_connect)()
    try:
        row = conn.execute(
            "SELECT base_url FROM feed_sources WHERE code = %s",
            (feed_source_code,),
        ).fetchone()
        conn.rollback()
    finally:
        conn.close()

    if row is None:
        raise PropertypostConfigError(
            f"no feed_sources row with code {feed_source_code!r} — PropertyPost "
            "agencies are seeded configuration (one row per agency, the full feed "
            "URL in base_url)."
        )

    feed_url = (row["base_url"] or "").strip()
    if not feed_url or not _has_file_path(feed_url):
        raise PropertypostConfigError(
            f"feed_sources row {feed_source_code!r} has no per-agency feed file in "
            "base_url — set it to the full URL, e.g. "
            f"'{resolve_propertypost_base_url()}/BstProperties.txt'."
        )

    return PropertypostSource(feed_source_code=feed_source_code, feed_url=feed_url)
