"""``rt3-import`` — pull one RT3 (Rawson) agency's province feeds into the DB.

Each agency is its own ``feed_sources`` row (``code='rt3-<agency>'``) with the
province URL tokens in ``auth_config->>'provinces'``. ``--province`` overrides
that list for a one-off run; ``--file Province=path`` replays a local file for one
province.

The feed is a full resend per province; a nightly pull is the right cadence:

    # crontab
    40 3 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers rt3-import --feed-source rt3-rawson \\
        >> /var/log/iol/rt3-rawson.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import Rt3APIError
from .source import Rt3ConfigError


def _parse_files(pairs: list[str] | None) -> dict[str, str] | None:
    if not pairs:
        return None
    out: dict[str, str] = {}
    for pair in pairs:
        province, _, path = pair.partition("=")
        if not province or not path:
            raise SystemExit(f"--file expects Province=path, got {pair!r}")
        out[province] = path
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rt3-import", description="Import an RT3 agency feed.")
    parser.add_argument("--feed-source", default="rt3", help="feed_sources.code (default: rt3)")
    parser.add_argument(
        "--province",
        action="append",
        default=None,
        help="province URL token (repeatable) — overrides the feed_sources list",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=None,
        metavar="PROVINCE=PATH",
        help="read a local feed file for one province (repeatable)",
    )
    parser.add_argument(
        "--max-listings", type=int, default=None, help="bound listings per province"
    )
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="do not withdraw listings absent from this pull",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch, parse and map only; no database writes"
    )
    args = parser.parse_args(argv)

    files = _parse_files(args.file)
    try:
        result = run(
            feed_source_code=args.feed_source,
            provinces=tuple(args.province) if args.province else None,
            files=files,
            max_listings=args.max_listings,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
        )
    except (Rt3ConfigError, Rt3APIError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
