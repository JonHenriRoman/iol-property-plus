"""Command-line entry point: `p24-suburbs download` and `p24-suburbs load`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from iol_importers.config import DOWNLOAD_DIR, resolve_database_url

from .property24.geography import (
    NaturalKeyCollisionError,
    UnknownProvinceError,
    build_desired,
)
from .property24.load import SchemaNotReadyError, load
from .property24.parse import EXPECTED_HEADER, HeaderMismatchError, parse_csv

# Operator-facing failures: print the message, skip the traceback, exit non-zero.
_CLEAN_ERRORS = (
    HeaderMismatchError,
    UnknownProvinceError,
    NaturalKeyCollisionError,
    SchemaNotReadyError,
    psycopg.OperationalError,
)

# The objective's expected South African row count. The feed drifts slightly over
# time; a move of more than ~1% is flagged and stops the run unless overridden.
EXPECTED_SA_COUNT = 20_754
DRIFT_TOLERANCE = 250


def _newest_download() -> Path | None:
    if not DOWNLOAD_DIR.is_dir():
        return None
    files = sorted(DOWNLOAD_DIR.glob("suburbs-*.csv"))
    return files[-1] if files else None


def _cmd_download(_args: argparse.Namespace) -> int:
    from .property24.download import FEED_URL, download

    print(f"GET {FEED_URL}")
    dest = download(DOWNLOAD_DIR)
    size = dest.stat().st_size
    print(f"saved {dest} ({size:,} bytes)")
    print("next: p24-suburbs load")
    return 0


def _cmd_load(args: argparse.Namespace) -> int:
    path = Path(args.file) if args.file else _newest_download()
    if path is None:
        print(
            f"no CSV found in {DOWNLOAD_DIR} — run `p24-suburbs download` first",
            file=sys.stderr,
        )
        return 2
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    print(f"parsing {path}")
    result = parse_csv(path)
    print(f"confirmed header: {','.join(EXPECTED_HEADER)}")

    print("\nfiltered out (not written anywhere):")
    for country, count in result.filtered_out:
        print(f"  {country:<24} {count:>7,}")
    total_filtered = sum(c for _, c in result.filtered_out)
    print(f"  {'TOTAL':<24} {total_filtered:>7,}")

    sa = result.south_africa_count
    delta = sa - EXPECTED_SA_COUNT
    print(f"\nSouth Africa rows: {sa:,} (expected ~{EXPECTED_SA_COUNT:,}, delta {delta:+,})")
    if abs(delta) > DRIFT_TOLERANCE:
        msg = (
            f"South African row count {sa:,} is more than {DRIFT_TOLERANCE} away from "
            f"the expected {EXPECTED_SA_COUNT:,}"
        )
        if not args.allow_count_drift:
            print(f"ABORT: {msg}. Re-run with --allow-count-drift once verified.", file=sys.stderr)
            return 3
        print(f"WARNING: {msg} (continuing: --allow-count-drift)", file=sys.stderr)

    desired = build_desired(result.rows)
    print(
        f"\nresolved: {len(desired.provinces)} provinces, "
        f"{len(desired.cities)} cities, {len(desired.suburbs)} suburbs"
    )

    url = resolve_database_url()
    print(f"connecting: {url.rsplit('@', 1)[-1]}")
    with psycopg.connect(url) as conn:
        report = load(conn, desired, dry_run=args.dry_run)

    verb = "would change" if args.dry_run else "committed"
    print(f"\n{verb}:")
    for name, counts in (
        ("provinces", report.provinces),
        ("cities", report.cities),
        ("suburbs", report.suburbs),
    ):
        print(
            f"  {name:<10} before={counts.before:>6,}  after={counts.after:>6,}  "
            f"inserted={counts.inserted:>6,}  updated={counts.updated:>5,}  "
            f"unchanged={counts.unchanged:>6,}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p24-suburbs",
        description="Seed provinces/cities/suburbs from Property24's canonical CSV (South Africa only).",  # noqa: E501
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="fetch the feed to a timestamped file in data/property24/")
    dl.set_defaults(func=_cmd_download)

    ld = sub.add_parser("load", help="parse a saved CSV and upsert South African rows")
    ld.add_argument("--file", help="CSV path (default: newest under data/property24/)")
    ld.add_argument("--dry-run", action="store_true", help="resolve and diff, then roll back")
    ld.add_argument(
        "--allow-count-drift",
        action="store_true",
        help="proceed even if the South African row count drifted past tolerance",
    )
    ld.set_defaults(func=_cmd_load)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except _CLEAN_ERRORS as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
