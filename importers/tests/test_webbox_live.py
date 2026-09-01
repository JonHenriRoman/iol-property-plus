"""Opt-in live test — a real Webbox fetch. Skipped unless WEBBOX_LIVE_DOMAIN +
WEBBOX_LIVE_SITEID + WEBBOX_LIVE_SECURITYKEY are set.

    WEBBOX_LIVE_DOMAIN=https://www.example.com WEBBOX_LIVE_SITEID=1799 \\
        WEBBOX_LIVE_SECURITYKEY=<key> \\
        uv run --project importers pytest -m live -k webbox

No database writes.
"""

from __future__ import annotations

import os

import pytest

from iol_importers.webbox.client import WebboxClient
from iol_importers.webbox.map import to_import_record
from iol_importers.webbox.parse import parse_feed

pytestmark = pytest.mark.live

_DOMAIN = os.environ.get("WEBBOX_LIVE_DOMAIN")
_SITEID = os.environ.get("WEBBOX_LIVE_SITEID")
_KEY = os.environ.get("WEBBOX_LIVE_SECURITYKEY")


@pytest.fixture
def creds() -> tuple[str, str, str]:
    if not (_DOMAIN and _SITEID and _KEY):
        pytest.skip("WEBBOX_LIVE_DOMAIN / _SITEID / _SECURITYKEY not all set")
    return _DOMAIN, _SITEID, _KEY


def test_real_feed_parses_and_maps(creds):
    domain, siteid, key = creds
    client = WebboxClient(base_url=domain)
    try:
        body = client.fetch(siteid, key)
    finally:
        client.close()

    parsed = parse_feed(body)
    assert len(parsed.properties) >= 1
    for prop in parsed.properties:
        out, _ = to_import_record(prop)
        assert out["vendor_listing_id"]
        assert out["listing_type"] in {"Sale", "Rent"}

    print(
        f"\nconfirmed outer XML form: {parsed.outer_form}  "
        f"({parsed.agencies_seen} <agency> element(s), {len(parsed.properties)} properties)"
    )
