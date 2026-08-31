"""Resolve one MyRoof franchise's feed parameters from its ``feed_sources`` row.

Each franchise is a separate ``feed_sources`` row. The opaque ``{token}`` path
segment of ``https://rat.myroof.co.za/{token}`` is the credential and lives in
``auth_config``:

    INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
    VALUES ('myroof-acme', 'Acme Realty (MyRoof)', 'MyRoof',
            'https://rat.myroof.co.za', '{"token": "<opaque>"}');

``auth_config ->> 'token'`` is the only per-franchise value. It never appears in
the source tree, an env var, a log line, or the run result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url, resolve_myroof_base_url


class MyroofConfigError(RuntimeError):
    """The feed_sources row is missing or has no auth_config->>'token'."""


@dataclass(frozen=True, slots=True)
class MyroofSource:
    feed_source_code: str
    token: str
    base_url: str


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def resolve_source(
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
) -> MyroofSource:
    """Read the franchise ``token`` (+ optional ``base_url`` override) off the
    ``feed_sources`` row. Read-only. Raises :class:`MyroofConfigError` when the row
    is absent or carries no ``token``."""
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
        raise MyroofConfigError(
            f"no feed_sources row with code {feed_source_code!r} — MyRoof franchises "
            "are seeded configuration (one row per franchise, the feed token in "
            "auth_config->>'token')."
        )

    token = str((row["auth_config"] or {}).get("token") or "").strip()
    if not token:
        raise MyroofConfigError(
            f"feed_sources row {feed_source_code!r} has no auth_config->>'token' "
            '— add it, e.g. \'{"token": "<opaque feed token>"}\'.'
        )

    base_url = (row["base_url"] or "").strip().rstrip("/") or resolve_myroof_base_url()
    return MyroofSource(feed_source_code=feed_source_code, token=token, base_url=base_url)
