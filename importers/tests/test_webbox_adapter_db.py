"""Opt-in DB test — the Webbox fixture round-trips through Step 14.

Scratch schema (dropped CASCADE); the client reads a local fixture file, no network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest -k webbox
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.webbox.adapter import run
from iol_importers.webbox.client import WebboxAPIError, WebboxClient
from iol_importers.webbox.source import WebboxConfigError, resolve_source
from webbox_mock import BASE_URL, mock_transport, set_body

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"
FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/webbox/fixtures/feed.xml"
_OPEN = "<property>"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _run(db, **kw):
    return run(
        feed_source_code=FEED,
        siteid="612",
        securitykey="demo-key",
        base_url=BASE_URL,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        **kw,
    )


def _feed_without(reference: str, tmp_path: Path) -> str:
    head, _, rest = FIXTURE.read_text().partition(_OPEN)
    blocks = (_OPEN + b for b in rest.split(_OPEN) if b.strip())
    kept = [b for b in blocks if f"<reference>{reference}</reference>" not in b]
    out = tmp_path / "feed.xml"
    out.write_text(head + "".join(kept))
    return str(out)


def _scalar(db, sql, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchone()["v"]


def test_fixture_imports_end_to_end(db):
    result = _run(db, file=str(FIXTURE))
    assert result.outer_form == "wrapped"
    assert result.agencies_seen == 1
    assert result.properties_in_feed == 5
    # 9001 (non-ZAR) -> validation reject; 9002 ("Boat House") -> mapping quarantine
    assert result.counts.inserted == 3
    assert result.counts.failed == 2
    assert result.non_zar_rejected == 1
    assert result.countries == {"South Africa": 4, "Namibia": 1}
    assert result.agent_counts == {"1": 4, "2": 1}
    assert result.unmapped_property_types == {"Boat House": 1}
    assert result.unknown_feature_tags == {"solar-geyser": 1}

    with db.connect() as conn:
        errs = {r["error_type"] for r in conn.execute("SELECT error_type FROM import_errors")}
    assert errs == {"validation", "mapping"}

    # reference.py enrichment ran before the import
    assert result.agencies_upserted == 1
    assert result.agents_upserted == 3
    assert (
        _scalar(
            db, "SELECT email AS v FROM agencies WHERE name = 'Valuables Properties - Bellville'"
        )
        == "info@valuables.co.za"
    )
    assert (
        _scalar(
            db,
            "SELECT (mobile || '|' || phone) AS v FROM agents a "
            "JOIN agent_vendor_ids m ON m.agent_id = a.id WHERE m.vendor_agent_id = '20733'",
        )
        == "0824936603|0219103525"
    )

    # Sale vs Rent field differences
    assert (
        _scalar(db, "SELECT erf_size_sqm AS v FROM listings WHERE vendor_listing_id = '1531'")
        == 589
    )
    assert (
        _scalar(db, "SELECT floor_size_sqm AS v FROM listings WHERE vendor_listing_id = '1597'")
        == 74
    )
    assert (
        _scalar(
            db,
            "SELECT raw_data->>'webbox_periodicity' AS v FROM listings "
            "WHERE vendor_listing_id = '1597'",
        )
        == "Per month"
    )
    assert (
        _scalar(
            db,
            "SELECT raw_data ? 'webbox_periodicity' AS v FROM listings "
            "WHERE vendor_listing_id = '1531'",
        )
        is False
    )
    # POA
    assert (
        _scalar(
            db, "SELECT price_on_application AS v FROM listings WHERE vendor_listing_id = '2678'"
        )
        is True
    )
    # multi-agent roster in raw_data
    assert (
        _scalar(
            db,
            "SELECT jsonb_array_length(raw_data->'webbox_agents') AS v FROM listings "
            "WHERE vendor_listing_id = '1531'",
        )
        == 2
    )
    # hotlinked media
    assert result.media_rows == _scalar(
        db, "SELECT count(*) AS v FROM listing_media WHERE media_type = 'Photo'"
    )
    assert result.media_rows >= 8


def test_rerun_creates_zero_duplicates(db):
    first = _run(db, file=str(FIXTURE))
    n1 = _scalar(db, "SELECT count(*) AS v FROM listings")
    second = _run(db, file=str(FIXTURE))
    n2 = _scalar(db, "SELECT count(*) AS v FROM listings")
    assert n1 == n2 == first.counts.inserted == 3
    assert second.counts.inserted == 0
    assert second.counts.updated == 3


def test_listing_absent_from_next_pull_is_withdrawn(db, tmp_path):
    _run(db, file=str(FIXTURE))
    result = _run(db, file=_feed_without("1597", tmp_path))
    assert result.withdrawn == 1
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute(
                "SELECT vendor_listing_id, status FROM listings "
                "WHERE vendor_listing_id IN ('1597', '1531')"
            ).fetchall()
        }
    assert rows["1597"] == "Withdrawn"
    assert rows["1531"] == "Active"
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 3  # nothing deleted


def test_broken_fetch_withdraws_nothing(db):
    _run(db, file=str(FIXTURE))
    client = WebboxClient(base_url=BASE_URL, transport=mock_transport(), retry_base_delay=0.0)
    set_body(b"<html>error</html>", content_type="text/html")
    with pytest.raises(WebboxAPIError):
        run(
            feed_source_code=FEED,
            siteid="612",
            securitykey="demo-key",
            base_url=BASE_URL,
            client=client,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
        )
    assert _scalar(db, "SELECT count(*) AS v FROM listings WHERE status = 'Active'") == 3


def test_dry_run_writes_nothing(db):
    result = _run(db, file=str(FIXTURE), dry_run=True)
    assert result.dry_run is True
    assert result.counts.seen == 5
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 0
    assert _scalar(db, "SELECT count(*) AS v FROM agents") == 0


def test_resolve_source_reads_siteid_and_key(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url, auth_config) "
            "VALUES ('webbox-x', 'Webbox X', 'https://x.test', "
            '\'{"siteid": "99", "securitykey": "abc"}\')'
        )
        conn.commit()
    src = resolve_source("webbox-x", connect=db.data_connect)
    assert (src.siteid, src.securitykey, src.base_url) == ("99", "abc", "https://x.test")


def test_resolve_source_missing_credential_raises(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url, auth_config) "
            "VALUES ('webbox-nokey', 'Webbox NoKey', 'https://x.test', '{\"siteid\": \"99\"}')"
        )
        conn.commit()
    with pytest.raises(WebboxConfigError):
        resolve_source("webbox-nokey", connect=db.data_connect)
