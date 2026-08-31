"""``myroof-import`` — pull one MyRoof franchise's feed into the DB.

Each franchise is its own ``feed_sources`` row (``code='myroof-<franchise>'``) with
the opaque feed token in ``auth_config->>'token'``. ``--token`` overrides that for
a one-off run before the row is seeded.

The feed is a full resend (~7.6 MB for a large franchise); a nightly pull is the
right cadence, not a short poll:

    # crontab
    20 3 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers myroof-import --feed-source myroof-acme \\
        >> /var/log/iol/myroof-acme.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import MyroofAPIError
from .source import MyroofConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="myroof-import", description="Import a MyRoof franchise feed."
    )
    parser.add_argument(
        "--feed-source", default="myroof", help="feed_sources.code (default: myroof)"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="feed token override — skips the feed_sources.auth_config lookup",
    )
    parser.add_argument("--file", default=None, help="read this local feed file instead of the URL")
    parser.add_argument("--max-listings", type=int, default=None, help="bound listings processed")
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="do not withdraw listings absent from this pull",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch, parse and map only; no database writes"
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            feed_source_code=args.feed_source,
            token=args.token,
            file=args.file,
            max_listings=args.max_listings,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
        )
    except (MyroofConfigError, MyroofAPIError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
