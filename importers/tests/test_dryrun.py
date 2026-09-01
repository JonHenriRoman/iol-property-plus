"""The JSON dry-run wrapper used by the /ops web UI (`iol_importers.dryrun`)."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys

import pytest

from iol_importers.dryrun import VENDORS, DryRunError, _jsonable, run

_NO_DRY_RUN = {"remax", "propdata", "propctrl"}


def test_registry_covers_every_adapter():
    assert len(VENDORS) == 11
    assert _NO_DRY_RUN.issubset(set(VENDORS))


@pytest.mark.parametrize("vendor", sorted(_NO_DRY_RUN))
def test_vendors_without_dry_run_return_a_sentinel(vendor):
    out = run(vendor, f"{vendor}-anything")
    assert out == {
        "vendor": vendor,
        "feed_source_code": f"{vendor}-anything",
        "supported": False,
        "ok": False,
        "message": f"{vendor} has no dry-run mode yet — test it from the CLI instead.",
    }


def test_unknown_vendor_raises():
    with pytest.raises(DryRunError):
        run("not-a-vendor", "x")


def test_jsonable_flattens_dataclasses_and_leaves_scalars():
    @dataclasses.dataclass
    class Inner:
        seen: int = 3

    @dataclasses.dataclass
    class Outer:
        counts: Inner
        tags: dict
        note: str

    assert _jsonable(Outer(Inner(), {"a": 1}, "x")) == {
        "counts": {"seen": 3},
        "tags": {"a": 1},
        "note": "x",
    }


def test_jsonable_stringifies_unknown_objects():
    assert _jsonable(object()).startswith("<object object")


@pytest.mark.dbtest
def test_missing_feed_source_row_is_a_failed_result_not_a_crash():
    out = run("allsa", "allsa-does-not-exist")
    assert out["ok"] is False
    assert out["supported"] is True
    assert out["error_type"] == "AllsaConfigError"


def test_cli_emits_one_json_line():
    proc = subprocess.run(
        [sys.executable, "-m", "iol_importers.dryrun", "propdata", "propdata-x", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False and payload["supported"] is False
