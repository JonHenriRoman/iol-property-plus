"""Opt-in live test — real calls to the Propdata API.

Not in the default run. Needs PROP_DATA_API_USERNAME / PROP_DATA_API_PASSWORD in
the environment or .env.local, and PROP_DATA_API_SITE for the client site.

    PROP_DATA_API_SITE=harcourts.co.za \\
        uv run --project importers pytest -m live
"""

from __future__ import annotations

import os

import pytest

from iol_importers.config import resolve_propdata_credentials
from iol_importers.propdata.adapter import CATEGORIES
from iol_importers.propdata.client import PropdataClient

pytestmark = pytest.mark.live


@pytest.fixture
def client(tmp_path):
    if resolve_propdata_credentials() is None:
        pytest.skip("Propdata credentials not configured")
    site = os.environ.get("PROP_DATA_API_SITE")
    if not site:
        pytest.skip("PROP_DATA_API_SITE not set")
    with PropdataClient(site, token_dir=tmp_path) as c:
        yield c


def test_login_then_renew_then_one_page_per_category(client):
    client.authenticate()
    assert client._token

    before = client._token
    client.renew()
    assert client._token and client._token != before  # renewed on the prior token alone

    for category in CATEGORIES:
        page = list(client.iter_listings(category, page_limit=1))
        assert isinstance(page, list)  # 200 + valid envelope (may be empty)
