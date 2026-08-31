"""Apply Fusion ``<Office>`` / ``<Agent>`` events to the canonical ``agencies`` /
``agents`` tables (and their ``*_vendor_ids`` maps).

A ``CreateOrUpdate`` / ``Snapshot`` is an idempotent upsert keyed on the Fusion
id: find the row via the vendor-id map and ``UPDATE`` it, else ``INSERT`` + map.
This also upgrades a name-only stub that ``resolve_agency`` / ``resolve_agent``
may have created for a listing that arrived before its Office/Agent event.

A ``Delete`` is a soft-delete — ``status = 'Inactive'`` — never a row removal.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

import psycopg

# Fusion Office accountStatus -> our agencies/agents status vocabulary.
_ACCOUNT_STATUS: dict[str, str] = {
    "Paying": "Active",
    "NotPaying": "Active",
    "Suspended": "Suspended",
    "Cancelled": "Inactive",
}

_SOFT_DELETE = {
    "Office": ("agencies", "agency_vendor_ids", "vendor_agency_id", "agency_id"),
    "Agent": ("agents", "agent_vendor_ids", "vendor_agent_id", "agent_id"),
}


def _t(element: Element, attr: str) -> str | None:
    value = (element.get(attr) or "").strip()
    return value or None


def _split_name(full: str | None) -> tuple[str, str]:
    parts = (full or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _agency_id_for_vendor(cur: psycopg.Cursor, feed_source_id: int, vendor_id: str) -> str | None:
    cur.execute(
        "SELECT agency_id FROM agency_vendor_ids "
        "WHERE feed_source_id = %s AND vendor_agency_id = %s",
        (feed_source_id, vendor_id),
    )
    row = cur.fetchone()
    return row["agency_id"] if row else None


def upsert_agency(cur: psycopg.Cursor, feed_source_id: int, office: Element) -> tuple[str, bool]:
    """Return ``(agency_id, created)``."""
    fusion_id = _t(office, "id")
    if fusion_id is None:
        raise ValueError("<Office> has no id")

    agency = _t(office, "agency")
    branch = _t(office, "branch")
    name = " — ".join(p for p in (agency, branch) if p) or fusion_id
    status = _ACCOUNT_STATUS.get(office.get("accountStatus") or "", "Active")
    fields = (name, branch, _t(office, "email"), _t(office, "tel"), _t(office, "address"), status)

    existing = _agency_id_for_vendor(cur, feed_source_id, fusion_id)
    if existing is not None:
        cur.execute(
            """
            UPDATE agencies
               SET name = %s, trading_name = %s, email = %s, phone = %s,
                   street_address = %s, status = %s, updated_at = now()
             WHERE id = %s
            """,
            (*fields, existing),
        )
        return existing, False

    cur.execute(
        """
        INSERT INTO agencies (name, trading_name, email, phone, street_address, status)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        fields,
    )
    agency_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO agency_vendor_ids (agency_id, feed_source_id, vendor_agency_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (feed_source_id, vendor_agency_id) DO NOTHING
        """,
        (agency_id, feed_source_id, fusion_id),
    )
    return agency_id, True


def upsert_agent(cur: psycopg.Cursor, feed_source_id: int, agent: Element) -> tuple[str, bool]:
    """Return ``(agent_id, created)``. Links to an agency via the first ``allOfficeIds`` entry."""
    fusion_id = _t(agent, "id")
    if fusion_id is None:
        raise ValueError("<Agent> has no id")

    first = _t(agent, "firstName")
    last = _t(agent, "surname")
    if not first and not last:
        first, last = _split_name(_t(agent, "title"))
    display = _t(agent, "title") or _t(agent, "team")

    agency_id: str | None = None
    for office_id in (agent.get("allOfficeIds") or "").split(","):
        office_id = office_id.strip()
        if office_id:
            agency_id = _agency_id_for_vendor(cur, feed_source_id, office_id)
            if agency_id is not None:
                break

    fields = (
        agency_id,
        first or "",
        last or "",
        display,
        _t(agent, "email"),
        _t(agent, "tel"),
        _t(agent, "cell"),
        _t(agent, "profilePicUrl2") or _t(agent, "profilePicUrl"),
        _t(agent, "blurb"),
    )

    cur.execute(
        "SELECT agent_id FROM agent_vendor_ids WHERE feed_source_id = %s AND vendor_agent_id = %s",
        (feed_source_id, fusion_id),
    )
    existing = cur.fetchone()
    if existing is not None:
        cur.execute(
            """
            UPDATE agents
               SET agency_id = COALESCE(%s, agency_id), first_name = %s, last_name = %s,
                   display_name = %s, email = %s, phone = %s, mobile = %s,
                   photo_url = %s, bio = %s, status = 'Active', updated_at = now()
             WHERE id = %s
            """,
            (*fields, existing["agent_id"]),
        )
        return existing["agent_id"], False

    cur.execute(
        """
        INSERT INTO agents
            (agency_id, first_name, last_name, display_name, email, phone, mobile, photo_url, bio)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        fields,
    )
    agent_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO agent_vendor_ids (agent_id, feed_source_id, vendor_agent_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (feed_source_id, vendor_agent_id) DO NOTHING
        """,
        (agent_id, feed_source_id, fusion_id),
    )
    return agent_id, True


def soft_delete(cur: psycopg.Cursor, feed_source_id: int, kind: str, ref_id: str) -> bool:
    """``<Delete><OfficeRef|AgentRef id>`` -> ``status = 'Inactive'``. Idempotent."""
    table, vid_table, vid_col, fk = _SOFT_DELETE[kind]
    cur.execute(
        f"""
        UPDATE {table} SET status = 'Inactive', updated_at = now()
         WHERE id = (
                 SELECT {fk} FROM {vid_table}
                 WHERE feed_source_id = %s AND {vid_col} = %s
               )
           AND status <> 'Inactive'
        """,
        (feed_source_id, str(ref_id)),
    )
    return cur.rowcount > 0
