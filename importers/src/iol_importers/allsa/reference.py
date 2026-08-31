"""Upsert AllSA offices (``BranchId``) and agents (``Agent_Email``) into the
canonical ``agencies`` / ``agents`` tables and their ``*_vendor_ids`` maps.

Modelled on :mod:`iol_importers.fusion.reference`: find the row via the vendor-id
map and ``UPDATE``, else ``INSERT`` + map. This also upgrades a name-only stub
that ``resolve_agency`` / ``resolve_agent`` would create for a listing processed
before its office/agent was seen.

One AllSA ``agencyid`` feed spans several ``BranchId`` offices (the real 10173
feed has four). Identity is ``BranchId`` — ``Agency_Location`` is the listing's
servicing town, not the office, and stays in ``listings.raw_data``.
"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg

from iol_importers.listings.normalize import split_person_name


def _v(mapping: Mapping[str, str], key: str) -> str | None:
    value = (mapping.get(key) or "").strip()
    return value or None


def _agency_id_for_vendor(cur: psycopg.Cursor, feed_source_id: int, vendor_id: str) -> str | None:
    row = cur.execute(
        "SELECT agency_id FROM agency_vendor_ids "
        "WHERE feed_source_id = %s AND vendor_agency_id = %s",
        (feed_source_id, vendor_id),
    ).fetchone()
    return row["agency_id"] if row else None


def upsert_agency(
    cur: psycopg.Cursor, feed_source_id: int, branch: Mapping[str, str]
) -> tuple[str, bool]:
    """``branch`` carries ``BranchId``, ``Agency``, ``Agency_Website``.
    Returns ``(agency_id, created)``."""
    branch_id = _v(branch, "BranchId")
    if branch_id is None:
        raise ValueError("branch has no BranchId")
    fields = (_v(branch, "Agency") or branch_id, _v(branch, "Agency_Website"))

    existing = _agency_id_for_vendor(cur, feed_source_id, branch_id)
    if existing is not None:
        cur.execute(
            "UPDATE agencies SET name = %s, website = %s, updated_at = now() WHERE id = %s",
            (*fields, existing),
        )
        return existing, False

    agency_id = cur.execute(
        "INSERT INTO agencies (name, website) VALUES (%s, %s) RETURNING id", fields
    ).fetchone()["id"]
    cur.execute(
        """
        INSERT INTO agency_vendor_ids (agency_id, feed_source_id, vendor_agency_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (feed_source_id, vendor_agency_id) DO NOTHING
        """,
        (agency_id, feed_source_id, branch_id),
    )
    return agency_id, True


def upsert_agent(
    cur: psycopg.Cursor,
    feed_source_id: int,
    agent: Mapping[str, str],
    agency_id: str | None,
) -> tuple[str, bool]:
    """``agent`` carries ``Agent_Email``, ``Agent_Name``, ``Agent_Cell``,
    ``Agent_Tel``. Keyed on the lower-cased email. Returns ``(agent_id, created)``."""
    email = (_v(agent, "Agent_Email") or "").lower() or None
    if email is None:
        raise ValueError("agent has no Agent_Email")

    first, last = split_person_name(_v(agent, "Agent_Name"))
    fields = (
        agency_id,
        first,
        last,
        _v(agent, "Agent_Name"),
        email,
        _v(agent, "Agent_Tel"),
        _v(agent, "Agent_Cell"),
    )

    existing = cur.execute(
        "SELECT agent_id FROM agent_vendor_ids WHERE feed_source_id = %s AND vendor_agent_id = %s",
        (feed_source_id, email),
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
        (agent_id, feed_source_id, email),
    )
    return agent_id, True
