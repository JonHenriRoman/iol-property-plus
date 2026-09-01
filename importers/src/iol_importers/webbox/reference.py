"""Upsert Webbox agencies (``agency-details/id``) and agents (``agent-id``) into
the canonical ``agencies`` / ``agents`` tables and their ``*_vendor_ids`` maps.

Modelled on :mod:`iol_importers.allsa.reference` / :mod:`iol_importers.fusion.reference`:
find the row via the vendor-id map and ``UPDATE``, else ``INSERT`` + map. This
also upgrades a name-only stub that ``import_listings``' own ``resolve_agency`` /
``resolve_agent`` would create for a listing processed before its agency/agent
was enriched — so the adapter runs this **before** ``import_listings``.

Webbox gives a numeric ``agent-id`` (the stable identity) alongside the agent's
email, so agents are keyed on ``agent-id``, not the email.
"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg

from iol_importers.listings.normalize import split_person_name


def _v(mapping: Mapping[str, str], key: str) -> str | None:
    value = (mapping.get(key) or "").strip()
    return value or None


def upsert_agency(
    cur: psycopg.Cursor, feed_source_id: int, agency: Mapping[str, str]
) -> tuple[str, bool]:
    """``agency`` is a flattened ``<agency-details>`` (``id``, ``name``, ``email``,
    ``landline``, ``logo-url``). Returns ``(agency_id, created)``."""
    vendor_id = _v(agency, "id")
    if vendor_id is None:
        raise ValueError("agency-details has no id")
    fields = (
        _v(agency, "name") or vendor_id,
        _v(agency, "email"),
        _v(agency, "landline"),
        _v(agency, "logo-url"),
    )

    existing = cur.execute(
        "SELECT agency_id FROM agency_vendor_ids "
        "WHERE feed_source_id = %s AND vendor_agency_id = %s",
        (feed_source_id, vendor_id),
    ).fetchone()
    if existing is not None:
        cur.execute(
            "UPDATE agencies SET name = %s, email = %s, phone = %s, website = %s, "
            "updated_at = now() WHERE id = %s",
            (*fields, existing["agency_id"]),
        )
        return existing["agency_id"], False

    agency_id = cur.execute(
        "INSERT INTO agencies (name, email, phone, website) VALUES (%s, %s, %s, %s) RETURNING id",
        fields,
    ).fetchone()["id"]
    cur.execute(
        """
        INSERT INTO agency_vendor_ids (agency_id, feed_source_id, vendor_agency_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (feed_source_id, vendor_agency_id) DO NOTHING
        """,
        (agency_id, feed_source_id, vendor_id),
    )
    return agency_id, True


def upsert_agent(
    cur: psycopg.Cursor,
    feed_source_id: int,
    agent: Mapping[str, str],
    agency_id: str | None,
) -> tuple[str, bool]:
    """``agent`` is a flattened ``<agent>`` (``agent-id``, ``firstname``,
    ``lastname``, ``email``, ``cellphone``, ``landline``, ``name``). Keyed on
    ``agent-id``. Returns ``(agent_id, created)``."""
    vendor_id = _v(agent, "agent-id")
    if vendor_id is None:
        raise ValueError("agent has no agent-id")

    first = _v(agent, "firstname")
    last = _v(agent, "lastname")
    if not first and not last:
        first, last = split_person_name(_v(agent, "name"))
    display = " ".join(p for p in (first, last) if p) or _v(agent, "name")
    fields = (
        agency_id,
        first or "",
        last or "",
        display,
        _v(agent, "email"),
        _v(agent, "landline"),
        _v(agent, "cellphone"),
    )

    existing = cur.execute(
        "SELECT agent_id FROM agent_vendor_ids WHERE feed_source_id = %s AND vendor_agent_id = %s",
        (feed_source_id, vendor_id),
    ).fetchone()
    if existing is not None:
        cur.execute(
            """
            UPDATE agents
               SET agency_id = COALESCE(%s, agency_id), first_name = %s, last_name = %s,
                   display_name = %s, email = %s, phone = %s, mobile = %s,
                   status = 'Active', updated_at = now()
             WHERE id = %s
            """,
            (*fields, existing["agent_id"]),
        )
        return existing["agent_id"], False

    agent_id = cur.execute(
        """
        INSERT INTO agents
            (agency_id, first_name, last_name, display_name, email, phone, mobile)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        fields,
    ).fetchone()["id"]
    cur.execute(
        """
        INSERT INTO agent_vendor_ids (agent_id, feed_source_id, vendor_agent_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (feed_source_id, vendor_agent_id) DO NOTHING
        """,
        (agent_id, feed_source_id, vendor_id),
    )
    return agent_id, True
