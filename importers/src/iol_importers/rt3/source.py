"""Resolve one RT3 (Rawson) agency's feed parameters from its ``feed_sources`` row.

RT3 publishes one bracket-KV file per province at
``{base_url}/iol-{Province}.txt`` (a plain public GET, no auth). Which provinces
an agency publishes is the only per-agency value, and it lives in ``auth_config``
as a JSON array of URL tokens:

    INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
    VALUES ('rt3-rawson', 'Rawson Properties (RT3)', 'RT3',
            'https://webservices.rawsonproperties.co.za',
            '{"provinces": ["Western_Cape", "Gauteng", "KwaZulu-Natal"]}');

The token is the exact ``{Province}`` segment of the URL (underscores for
spaces): ``Western_Cape`` -> ``.../iol-Western_Cape.txt``. There is no
credential.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url, resolve_rt3_base_url


class Rt3ConfigError(RuntimeError):
    """The feed_sources row is missing or has no auth_config->>'provinces' list."""


@dataclass(frozen=True, slots=True)
class Rt3Source:
    feed_source_code: str
    base_url: str
    provinces: tuple[str, ...]


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _clean_provinces(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(p).strip() for p in raw if str(p).strip()))


def resolve_source(
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
) -> Rt3Source:
    """Read the province list (+ optional ``base_url`` override) off the
    ``feed_sources`` row. Read-only. Raises :class:`Rt3ConfigError` when the row is
    absent or carries no non-empty ``auth_config->>'provinces'`` array."""
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
        raise Rt3ConfigError(
            f"no feed_sources row with code {feed_source_code!r} — RT3 agencies "
            "are seeded configuration (one row per agency, the province list in "
            "auth_config->>'provinces')."
        )

    provinces = _clean_provinces((row["auth_config"] or {}).get("provinces"))
    if not provinces:
        raise Rt3ConfigError(
            f"feed_sources row {feed_source_code!r} has no auth_config->>'provinces' "
            '— add the URL tokens, e.g. \'{"provinces": ["Western_Cape", "Gauteng"]}\'.'
        )

    base_url = (row["base_url"] or "").strip().rstrip("/") or resolve_rt3_base_url()
    return Rt3Source(feed_source_code=feed_source_code, base_url=base_url, provinces=provinces)
