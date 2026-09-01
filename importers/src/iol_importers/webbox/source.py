"""Resolve one Webbox site's feed parameters from its ``feed_sources`` row.

Webbox publishes one XML file per site at
``{domain}/template/feeds,WebboxFeedForSite.vm/siteid/{siteid}/securitykey/{securitykey}/feed.xml``
— a plain GET where the URL itself is the credential. The per-agency values are
the domain (``base_url``) and the ``siteid`` / ``securitykey`` pair
(``auth_config``):

    INSERT INTO feed_sources (code, name, vendor_name, base_url, auth_config)
    VALUES ('webbox-valuables', 'Valuables Properties (Webbox)', 'Webbox',
            'https://www.valuablesproperties.co.za',
            '{"siteid": "612", "securitykey": "<opaque key>"}');

Neither ``siteid`` nor ``securitykey`` ever appears in the source tree, an env
var, a log line, or the run result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url


class WebboxConfigError(RuntimeError):
    """The feed_sources row is missing, has no base_url, or lacks siteid/securitykey."""


@dataclass(frozen=True, slots=True)
class WebboxSource:
    feed_source_code: str
    base_url: str
    siteid: str
    securitykey: str


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def resolve_source(
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
) -> WebboxSource:
    """Read the site domain + ``siteid`` / ``securitykey`` off the ``feed_sources``
    row. Read-only. Raises :class:`WebboxConfigError` when the row is absent, has
    no ``base_url``, or is missing either credential in ``auth_config``."""
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
        raise WebboxConfigError(
            f"no feed_sources row with code {feed_source_code!r} — Webbox sites are "
            "seeded configuration (one row per site: the domain in base_url, "
            "siteid + securitykey in auth_config)."
        )

    base_url = (row["base_url"] or "").strip().rstrip("/")
    if not base_url:
        raise WebboxConfigError(
            f"feed_sources row {feed_source_code!r} has no base_url — set it to the "
            "site domain, e.g. 'https://www.valuablesproperties.co.za'."
        )

    auth_config = row["auth_config"] or {}
    siteid = str(auth_config.get("siteid") or "").strip()
    securitykey = str(auth_config.get("securitykey") or "").strip()
    if not siteid or not securitykey:
        raise WebboxConfigError(
            f"feed_sources row {feed_source_code!r} needs both auth_config->>'siteid' "
            'and auth_config->>\'securitykey\' — e.g. \'{"siteid": "612", '
            '"securitykey": "<opaque key>"}\'.'
        )

    return WebboxSource(
        feed_source_code=feed_source_code,
        base_url=base_url,
        siteid=siteid,
        securitykey=securitykey,
    )
