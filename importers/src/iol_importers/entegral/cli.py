"""``entegral-import`` — pull Entegral listings into the database via the importer.

Auth: HTTP Basic on every request. Needs, in .env.local: ENTEGRAL_USERNAME,
ENTEGRAL_PASSWORD (ENTEGRAL_API_BASE_URL optional, defaults to
https://sync.entegral.net/api).

The run calls ``officeslist`` first, then ``officelistings`` once per office,
imports each office's listings, re-hosts their photos, and reconciles
(soft-deletes listings absent from an office's response).

Scheduling (nothing in this repo wires it — see the root README's "Not yet
implemented"). Entegral's feed updates twice a day and requires a poll at least
every 24 hours; run it every 12 hours to catch both updates:

    # crontab
    0 */12 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers entegral-import >> /var/log/iol/entegral.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import EntegralAuthError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="entegral-import",
        description="Import Entegral office listings and reconcile removals.",
    )
    parser.add_argument(
        "--feed-source", default="entegral", help="feed_sources.code (default: entegral)"
    )
    parser.add_argument(
        "--office",
        "-o",
        action="append",
        dest="offices",
        default=None,
        help="restrict to this officereference (repeatable)",
    )
    parser.add_argument("--max-offices", type=int, default=None, help="bound offices processed")
    parser.add_argument("--max-listings", type=int, default=None, help="bound listings per office")
    parser.add_argument("--no-media", action="store_true", help="skip photo download / re-host")
    parser.add_argument(
        "--refresh-media", action="store_true", help="re-download photos, ignoring the URL index"
    )
    parser.add_argument(
        "--no-reconcile", action="store_true", help="do not withdraw listings absent from a feed"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and map only; no database writes"
    )
    parser.add_argument(
        "--no-checkpoint", action="store_true", help="do not advance data/entegral/last-sync.json"
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            feed_source_code=args.feed_source,
            office_refs=args.offices,
            max_offices=args.max_offices,
            max_listings_per_office=args.max_listings,
            with_media=not args.no_media,
            refresh_media=args.refresh_media,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
            write_checkpoint=not args.no_checkpoint,
        )
    except EntegralAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
