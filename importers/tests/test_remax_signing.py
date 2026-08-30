"""Offline tests for the RE/MAX SigV4 signer."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac

import pytest

from iol_importers.remax.signing import sign_headers

_ACCESS = "AKIDEXAMPLE"
_SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
_NOW = dt.datetime(2015, 8, 30, 12, 36, 0, tzinfo=dt.UTC)
_URL = "https://ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com/feeds_default/lists"


def _independent_signature(body: bytes, amzdate: str, datestamp: str) -> str:
    """Re-derive the signature by hand — an oracle independent of signing.py's structure."""
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        [
            "POST",
            "/feeds_default/lists",
            "",
            f"host:ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com\n"
            f"x-amz-content-sha256:{payload_hash}\nx-amz-date:{amzdate}\n",
            "host;x-amz-content-sha256;x-amz-date",
            payload_hash,
        ]
    )
    scope = f"{datestamp}/eu-west-1/execute-api/aws4_request"
    sts = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amzdate,
            scope,
            hashlib.sha256(canonical.encode()).hexdigest(),
        ]
    )

    def _h(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k = _h(
        _h(_h(_h(f"AWS4{_SECRET}".encode(), datestamp), "eu-west-1"), "execute-api"), "aws4_request"
    )
    return hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()


def test_signature_matches_an_independent_derivation():
    body = b'{"token":"k","offices":true}'
    headers = sign_headers(
        method="POST", url=_URL, body=body, access_key=_ACCESS, secret_key=_SECRET, now=_NOW
    )
    assert headers["X-Amz-Date"] == "20150830T123600Z"
    assert headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
    expected = _independent_signature(body, "20150830T123600Z", "20150830")
    assert f"Signature={expected}" in headers["Authorization"]
    assert headers["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/eu-west-1/execute-api/aws4_request"
    )


def test_signature_is_stable_for_fixed_input():
    body = b'{"token":"k","offices":true}'
    a = sign_headers(
        method="POST", url=_URL, body=body, access_key=_ACCESS, secret_key=_SECRET, now=_NOW
    )
    b = sign_headers(
        method="POST", url=_URL, body=body, access_key=_ACCESS, secret_key=_SECRET, now=_NOW
    )
    assert a == b


@pytest.mark.parametrize("mutate", ["body", "time"])
def test_signature_changes_with_input(mutate):
    base = sign_headers(
        method="POST", url=_URL, body=b"{}", access_key=_ACCESS, secret_key=_SECRET, now=_NOW
    )
    if mutate == "body":
        other = sign_headers(
            method="POST",
            url=_URL,
            body=b'{"x":1}',
            access_key=_ACCESS,
            secret_key=_SECRET,
            now=_NOW,
        )
    else:
        other = sign_headers(
            method="POST",
            url=_URL,
            body=b"{}",
            access_key=_ACCESS,
            secret_key=_SECRET,
            now=_NOW + dt.timedelta(hours=1),
        )
    assert base["Authorization"] != other["Authorization"]


def test_secret_never_appears_in_output():
    headers = sign_headers(
        method="POST", url=_URL, body=b"{}", access_key=_ACCESS, secret_key=_SECRET, now=_NOW
    )
    blob = " ".join(headers.values())
    assert _SECRET not in blob
