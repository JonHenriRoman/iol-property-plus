"""Foreign-key resolution for a vendor listing record, against the data connection.

Every resolver runs inside the importer's per-record transaction, so any row it
creates (a canonical agency/agent, a property-type mapping) is rolled back with
the record if a later step fails.
"""

from __future__ import annotations

import psycopg

from .normalize import clean_str, split_person_name


class MappingError(RuntimeError):
    """A vendor value could not be mapped to a canonical row — error_type='mapping'."""


def resolve_property_type(
    cur: psycopg.Cursor,
    feed_source_id: int,
    vendor_value: object,
    vendor_listing_type: object = None,
) -> int:
    """Resolve a vendor property-type string to a property_types.id.

    Order: existing per-feed mapping row -> case-insensitive property_types.name
    match (persisting the mapping) -> MappingError. Never creates a property_types
    row; the canonical list is curated.

    ``vendor_listing_type`` (e.g. "residential", "commercial") namespaces the
    mapping key, so a feed that sends the same property-type word in different
    listing categories can map each to a different canonical type explicitly. The
    name-match fallback still uses the bare value.
    """
    value = clean_str(vendor_value)
    if value is None:
        raise MappingError("property_type is missing")
    namespace = clean_str(vendor_listing_type)
    mapping_key = f"{namespace}:{value}" if namespace else value

    cur.execute(
        """
        SELECT property_type_id
        FROM property_type_vendor_mappings
        WHERE feed_source_id = %s AND vendor_value = %s
        """,
        (feed_source_id, mapping_key),
    )
    row = cur.fetchone()
    if row is not None:
        return row["property_type_id"]

    cur.execute("SELECT id FROM property_types WHERE name ILIKE %s", (value,))
    row = cur.fetchone()
    if row is None:
        raise MappingError(
            f"no property_types row matches {value!r} and no mapping exists for "
            f"feed_source_id={feed_source_id}"
            + (f" (listing type {namespace!r})" if namespace else "")
        )

    property_type_id = row["id"]
    cur.execute(
        """
        INSERT INTO property_type_vendor_mappings (feed_source_id, vendor_value, property_type_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (feed_source_id, vendor_value) DO NOTHING
        """,
        (feed_source_id, mapping_key, property_type_id),
    )
    return property_type_id


def resolve_suburb(cur: psycopg.Cursor, name: object, extension: object = None) -> int | None:
    """Resolve a vendor suburb name to suburbs.id, or None when unresolved.

    Tries an exact name match (with and without the vendor's extension), then an
    alternate-name match. Returns None rather than guessing — the listing still
    imports with suburb_id NULL.
    """
    suburb_name = clean_str(name)
    if suburb_name is None:
        return None
    ext = clean_str(extension)

    candidates = [suburb_name]
    if ext:
        candidates.append(f"{suburb_name} {ext}")

    cur.execute(
        "SELECT id FROM suburbs WHERE lower(name) = ANY(%s) ORDER BY id LIMIT 1",
        ([c.lower() for c in candidates],),
    )
    row = cur.fetchone()
    if row is not None:
        return row["id"]

    # alternate_names is a single pipe-tolerant free-text value (migration 001).
    cur.execute(
        """
        SELECT id
        FROM suburbs
        WHERE alternate_names IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM unnest(regexp_split_to_array(alternate_names, '\\s*\\|\\s*')) AS alt
              WHERE lower(trim(alt)) = lower(%s)
          )
        ORDER BY id
        LIMIT 1
        """,
        (suburb_name,),
    )
    row = cur.fetchone()
    return row["id"] if row is not None else None


def resolve_agency(
    cur: psycopg.Cursor,
    feed_source_id: int,
    vendor_agency_id: object,
    name: object,
) -> str | None:
    """Resolve via agency_vendor_ids (feed_source_id, vendor_agency_id); create a
    canonical agencies row + mapping only when no mapping exists yet."""
    vendor_id = clean_str(vendor_agency_id)
    agency_name = clean_str(name)
    if vendor_id is None and agency_name is None:
        return None

    if vendor_id is not None:
        cur.execute(
            """
            SELECT agency_id
            FROM agency_vendor_ids
            WHERE feed_source_id = %s AND vendor_agency_id = %s
            """,
            (feed_source_id, vendor_id),
        )
        row = cur.fetchone()
        if row is not None:
            return row["agency_id"]

    cur.execute(
        "INSERT INTO agencies (name) VALUES (%s) RETURNING id",
        (agency_name or vendor_id,),
    )
    agency_id = cur.fetchone()["id"]

    if vendor_id is not None:
        cur.execute(
            """
            INSERT INTO agency_vendor_ids (agency_id, feed_source_id, vendor_agency_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (feed_source_id, vendor_agency_id) DO NOTHING
            """,
            (agency_id, feed_source_id, vendor_id),
        )
    return agency_id


def resolve_agent(
    cur: psycopg.Cursor,
    feed_source_id: int,
    vendor_agent_id: object,
    name: object,
    agency_id: str | None,
) -> str | None:
    """Resolve via agent_vendor_ids (feed_source_id, vendor_agent_id); create a
    canonical agents row + mapping only when no mapping exists yet."""
    vendor_id = clean_str(vendor_agent_id)
    agent_name = clean_str(name)
    if vendor_id is None and agent_name is None:
        return None

    if vendor_id is not None:
        cur.execute(
            """
            SELECT agent_id
            FROM agent_vendor_ids
            WHERE feed_source_id = %s AND vendor_agent_id = %s
            """,
            (feed_source_id, vendor_id),
        )
        row = cur.fetchone()
        if row is not None:
            return row["agent_id"]

    first, last = split_person_name(agent_name or vendor_id)
    cur.execute(
        "INSERT INTO agents (agency_id, first_name, last_name) VALUES (%s, %s, %s) RETURNING id",
        (agency_id, first, last),
    )
    agent_id = cur.fetchone()["id"]

    if vendor_id is not None:
        cur.execute(
            """
            INSERT INTO agent_vendor_ids (agent_id, feed_source_id, vendor_agent_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (feed_source_id, vendor_agent_id) DO NOTHING
            """,
            (agent_id, feed_source_id, vendor_id),
        )
    return agent_id
