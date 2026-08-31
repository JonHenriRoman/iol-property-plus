"""The Gumtree Pro "Standards and Conventions" checks, in two tiers.

**Per-record, rejecting** — a breach sets ``__validation_error__`` on the mapped
record, which the Step 14 importer turns into an ``import_errors`` row with
``error_type='validation'`` and no listing written. These are the rules that
speak to a value being wrong: a malformed date, a bad email, spaces in a phone
number, an unknown ``Type``, an unknown ``Status``, no geography at all.

**Per-run, warning** — the doc also mandates Pascal-cased tag names and no
underscores in field names. The real PropertyEngine feed violates the first
outright (``status``, ``agent``, ``email`` are lowercase). Rejecting every record
over casing would quarantine 100% of the observed feed — a broken importer, not a
strict one — so these are counted once per run and logged, never rejected.

:func:`validate_record` returns ``None`` when the record is importable, or a
human-readable reason string when it must be rejected. :func:`run_warnings`
inspects the whole batch of raw records and returns ``{rule: count}``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .decode import as_list, get

# The doc's own vocabularies (Appendix B `Type`; the `Status` enum). Compared
# case-insensitively. Kept here, not in map.py, so "is this even a valid value"
# is answered before any mapping is attempted.
VALID_TYPES: frozenset[str] = frozenset(
    t.lower()
    for t in (
        # Appendix B — Basic types
        "Apartment", "Cluster", "Farm", "Flat", "House", "Office", "Small Holding",
        "Townhouse", "Vacant Land",
        # Appendix B — Speciality types
        "Apartment Block", "Bed & Breakfast", "Building", "Bungalow", "Business",
        "Duplex", "Equestrian Property", "Factory", "Freehold", "Freestanding",
        "Garden Cottage", "Gated Estate", "Guest House", "Guesthouse", "Hotel",
        "Hotel Room", "Industrial Yard", "Investment", "Mini Factory", "Minifactory",
        "Penthouse", "Place Of Worship", "Retail", "Room", "Sectional Title",
        "Serviced Office", "Showroom", "Simplex", "Storage Unit", "Studio Apartment",
        "Villa", "Warehouse",
    )
)

VALID_STATUSES: frozenset[str] = frozenset({"for sale", "to let", "holiday"})

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
# RFC 5322 in full is impractical; this is the pragmatic subset every mail
# validator ships — one @, a dot-separated domain, no spaces.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_record(record: dict[str, Any]) -> str | None:
    """Return a rejection reason, or ``None`` when the record may be imported."""
    if _text(get(record, "UniqueID")) is None:
        return "UniqueID is missing or blank — there is no vendor listing id to upsert on"

    heading = _text(get(record, "Heading"))
    if heading is None:
        return "Heading is missing or blank — listings.title is required"

    type_value = _text(get(record, "Type"))
    if type_value is None:
        return "Type is missing — it must be one of the Appendix B vocabulary"
    if type_value.lower() not in VALID_TYPES:
        return f"Type {type_value!r} is not in the Appendix B vocabulary"

    status_value = _text(get(record, "Status", "status"))
    if status_value is None:
        return "Status is missing — expected 'For Sale', 'To Let' or 'Holiday'"
    if status_value.lower() not in VALID_STATUSES:
        return f"Status {status_value!r} is not 'For Sale', 'To Let' or 'Holiday'"

    for field in ("CreatedOn", "UpdatedOn"):
        raw = _text(get(record, field))
        if raw is not None and not _is_iso_datetime(raw):
            return f"{field} {raw!r} is not in yyyy-mm-dd HH:mm:ss format"

    geo_error = _geography_error(record)
    if geo_error is not None:
        return geo_error

    contact_error = _contact_error(record)
    if contact_error is not None:
        return contact_error

    return None


def _is_iso_datetime(value: str) -> bool:
    try:
        datetime.strptime(value, _DATE_FORMAT)
        return True
    except ValueError:
        return False


def _geography_error(record: dict[str, Any]) -> str | None:
    if _text(get(record, "Location")) is not None:
        return None
    missing = [
        name
        for name, value in (
            ("Suburb", get(record, "Suburb")),
            ("City", get(record, "City", "CityTown")),
            ("Province", get(record, "Province")),
        )
        if _text(value) is None
    ]
    if missing:
        return (
            "no Location, and " + "/".join(missing) + " missing — the doc requires "
            "Suburb, City and Province when Location is absent"
        )
    return None


def _contact_error(record: dict[str, Any]) -> str | None:
    for agent_wrap in as_list(get(record, "Agents")):
        agent = get(agent_wrap, "Agent", "agent") or agent_wrap
        phone = _text(get(agent, "AgentPhone"))
        if phone is not None and " " in phone:
            return f"AgentPhone {phone!r} contains a space — phone numbers must have none"
        email = _text(get(agent, "AgentEmail"))
        if email is not None and not _EMAIL_RE.match(email):
            return f"AgentEmail {email!r} is not a valid email address"
    office = get(record, "Office")
    office_email = _text(get(office, "Email", "email"))
    if office_email is not None and not _EMAIL_RE.match(office_email):
        return f"Office Email {office_email!r} is not a valid email address"
    return None


# -- per-run warnings ------------------------------------------------------

WARNING_RULES = ("non_pascal_tag_names", "underscore_in_field_names")


def run_warnings(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count convention breaches across the batch. Never rejects anything."""
    counts = dict.fromkeys(WARNING_RULES, 0)
    for record in records:
        flags = _record_convention_flags(record)
        for rule in WARNING_RULES:
            if flags[rule]:
                counts[rule] += 1
    return counts


def _record_convention_flags(record: Any, _depth: int = 0) -> dict[str, bool]:
    flags = dict.fromkeys(WARNING_RULES, False)
    if not isinstance(record, dict) or _depth > 6:
        return flags
    for key, value in record.items():
        if not isinstance(key, str):
            continue
        if "_" in key:
            flags["underscore_in_field_names"] = True
        if not _PASCAL_RE.match(key):
            flags["non_pascal_tag_names"] = True
        for child in (value, *(as_list(value) if isinstance(value, list) else ())):
            child_flags = _record_convention_flags(child, _depth + 1)
            for rule in WARNING_RULES:
                flags[rule] = flags[rule] or child_flags[rule]
    return flags
