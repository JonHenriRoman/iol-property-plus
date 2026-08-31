"""Resolve one AllSA agency's feed parameters from its ``feed_sources`` row.

Each AllSA agency is a separate ``feed_sources`` row:

    INSERT INTO feed_sources (code, name, vendor_name, format, base_url, auth_config)
    VALUES ('allsa-10173', 'National Real Estate', 'AllSA Property', 'XML',
            'https://www.allsaproperty.co.za/feeds/iol.ashx',
            '{"agency_id": "10173"}');

``auth_config ->> 'agency_id'`` is the ``agencyid`` query parameter — the only
per-agency value the adapter needs. Adding an agency is one seeded row, no code
change, and no agency id ever appears in the source tree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_allsa_base_url, resolve_database_url


class AllsaConfigError(RuntimeError):
    """The feed_sources row is missing or has no auth_config->>'agency_id'."""


@dataclass(frozen=True, slots=True)
class AllsaSource:
    feed_source_code: str
    agency_id: str
    base_url: str


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def resolve_source(
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
) -> AllsaSource:
    """Read ``agency_id`` (+ optional ``base_url`` override) off the feed_sources row.

    Read-only. Raises :class:`AllsaConfigError` when the row does not exist or has
    no ``agency_id`` in ``auth_config``.
    """
    conn = (connect or _default_connect)()
    try:
        row = conn.execute(
            "SELECT base_url, auth_config FROM feed_sources WHERE code = %s",
            (feed_source_code,),
        ).fetchone()
        conn.rollback()
    finally:
        conn.close()

    if row is None:
        raise AllsaConfigError(
            f"no feed_sources row with code {feed_source_code!r} — AllSA agencies "
            "are seeded configuration (one row per agency, agencyid in "
            "auth_config->>'agency_id')."
        )

    auth_config = row["auth_config"] or {}
    agency_id = str(auth_config.get("agency_id") or "").strip()
    if not agency_id:
        raise AllsaConfigError(
            f"feed_sources row {feed_source_code!r} has no auth_config->>'agency_id' "
            '— add it, e.g. \'{"agency_id": "10173"}\'.'
        )

    base_url = (row["base_url"] or "").strip() or resolve_allsa_base_url()
    return AllsaSource(feed_source_code=feed_source_code, agency_id=agency_id, base_url=base_url)
