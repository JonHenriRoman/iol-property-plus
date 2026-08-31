"""Opt-in live test — a real GET of the PropertyEngine feed, shapes only.

Skipped until PropertyEngine gives us a URL (``PROPERTYENGINE_FEED_URL``). No
database writes — this only fetches and decodes.

    uv run --project importers pytest -m live
"""

from __future__ import annotations

import pytest

from iol_importers.config import resolve_propertyengine_feed
from iol_importers.propertyengine.client import PropertyEngineClient
from iol_importers.propertyengine.decode import parse_feed
from iol_importers.propertyengine.map import to_import_record

pytestmark = pytest.mark.live


@pytest.fixture
def feed():
    resolved = resolve_propertyengine_feed()
    if resolved is None:
        pytest.skip("PROPERTYENGINE_FEED_URL not set — still pending from PropertyEngine")
    return resolved


def test_feed_fetches_decodes_and_maps(feed):
    with PropertyEngineClient(feed=feed) as client:
        body, content_type = client.fetch()

    records = parse_feed(body, content_type)
    assert records, "feed returned no Property records"

    mapped = 0
    for raw in records[:50]:
        record, urls = to_import_record(raw)
        assert record["vendor_listing_id"]
        assert isinstance(urls, list)
        mapped += 1
    assert mapped > 0
