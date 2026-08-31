"""Fusion SecurityToken generation.

Every Fusion call carries four query-string parameters — ``clientId``,
``timeStamp``, ``salt``, ``digest``. Tokens are **not reusable**: a fresh one is
generated for every request (and every retry). Per the doc's pseudocode:

    KeyString = TimeStamp + "*" + Password + "*" + Salt
    Digest    = Base64(SHA1(Utf8(KeyString)))

The password is fed straight into the digest but is still a raw credential — it
is never logged and never leaves this module or the client's private attribute.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime

_TIMESTAMP_FMT = "%Y-%m-%d-%H-%M"


def make_salt() -> str:
    """A 64-bit random number as a base-10 string, per the doc."""
    return str(secrets.randbits(64))


def digest(timestamp: str, password: str, salt: str) -> str:
    """Base64(SHA1(utf8(``timestamp*password*salt``)))."""
    key = f"{timestamp}*{password}*{salt}".encode()
    return base64.b64encode(hashlib.sha1(key).digest()).decode("ascii")


def security_params(
    client_id: int,
    password: str,
    *,
    now: datetime | None = None,
    salt: str | None = None,
) -> dict[str, str]:
    """The four query-string params for one Fusion call. Fresh every call.

    ``now`` and ``salt`` are injectable for deterministic tests only; production
    callers pass neither.
    """
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime(_TIMESTAMP_FMT)
    salt = salt or make_salt()
    return {
        "clientId": str(client_id),
        "timeStamp": timestamp,
        "salt": salt,
        "digest": digest(timestamp, password, salt),
    }
