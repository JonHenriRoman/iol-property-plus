"""AWS Signature Version 4 for the RE/MAX feed (``execute-api``, ``eu-west-1``).

The RE/MAX feed is an API Gateway deployment authenticated with IAM — every
request must be SigV4-signed. A dedicated dependency (``botocore``) would be
heavier than the signing itself, which is ~1 page of deterministic ``hmac`` /
``hashlib`` and is fully unit-testable offline against the published AWS test
vectors.

``sign_headers`` is a pure function: give it the request and a fixed ``now`` and
it returns the exact headers to add. Nothing here reads the environment, logs, or
mutates anything.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
from urllib.parse import quote, urlsplit

_ALGORITHM = "AWS4-HMAC-SHA256"
_UNRESERVED_PATH = "/-._~"  # RFC 3986 unreserved, plus '/' which stays literal in a path


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _hmac(f"AWS4{secret}".encode(), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def sign_headers(
    *,
    method: str,
    url: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str = "eu-west-1",
    service: str = "execute-api",
    now: dt.datetime | None = None,
) -> dict[str, str]:
    """Return the SigV4 headers to add to the request.

    Keys: ``Authorization``, ``X-Amz-Date``, ``x-amz-content-sha256``. The caller
    still adds ``x-api-key`` and sends the body unchanged.
    """
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is not None:
        now = now.astimezone(dt.UTC).replace(tzinfo=None)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    parts = urlsplit(url)
    host = parts.netloc
    canonical_uri = quote(parts.path or "/", safe=_UNRESERVED_PATH)
    canonical_querystring = parts.query  # the RE/MAX endpoints take no query string
    payload_hash = _sha256_hex(body)

    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amzdate}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [_ALGORITHM, amzdate, scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    authorization = (
        f"{_ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "X-Amz-Date": amzdate,
        "x-amz-content-sha256": payload_hash,
    }
