"""Opt-in live test — a real signed pull against the Entegral sandbox.

Skipped unless ENTEGRAL_USERNAME / ENTEGRAL_PASSWORD resolve. Shapes only; no
database writes.

    uv run --project importers pytest -m live
"""

from __future__ import annotations

import pytest

from iol_importers.config import resolve_entegral_credentials
from iol_importers.entegral.client import EntegralClient, office_reference
from iol_importers.entegral.map import photo_urls, to_import_record

pytestmark = pytest.mark.live


@pytest.fixture
def client():
    if resolve_entegral_credentials() is None:
        pytest.skip("ENTEGRAL_USERNAME / ENTEGRAL_PASSWORD not set")
    with EntegralClient() as c:
        yield c


def test_officeslist_returns_references(client):
    offices = client.list_offices()
    assert offices, "sandbox returned no offices"
    assert any(office_reference(o) for o in offices)


def test_one_office_listings_map(client):
    offices = client.list_offices()
    ref = next(office_reference(o) for o in offices if office_reference(o))
    office = next(o for o in offices if office_reference(o) == ref)

    listings = client.office_listings(ref)
    if not listings:
        pytest.skip(f"office {ref} has no listings right now")

    record, urls = to_import_record(listings[0], office=office)
    assert record["vendor_listing_id"]
    assert isinstance(urls, list)
    assert photo_urls(listings[0]) == urls
