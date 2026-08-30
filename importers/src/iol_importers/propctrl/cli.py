"""``propctrl-import`` — pull PropCtrl listings into the database via the importer.

Auth: HTTP Basic on every request (``base64(username:password)``); no session
token. Needs, in .env.local: PROPCTRL_API_USERNAME, PROPCTRL_API_PASSWORD
(PROPCTRL_API_BASE_URL optional, defaults to https://api.propctrl.com).

A normal run resumes from the checkpoint in ``data/propctrl/checkpoint.json``.
``--from-date`` overrides it; ``--max-listings`` bounds a run; ``--no-checkpoint``
processes without advancing the cursor.
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import PropctrlAuthError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="propctrl-import",
        description="Import PropCtrl listings from the change feed.",
    )
    parser.add_argument(
        "--feed-source",
        default="propctrl",
        help="feed_sources.code to attribute the import to (default: propctrl)",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="ISO-8601 timestamp; overrides the persisted checkpoint",
    )
    parser.add_argument(
        "--max-listings",
        type=int,
        default=None,
        help="stop after N candidate listings (bounded run)",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="do not advance data/propctrl/checkpoint.json",
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            feed_source_code=args.feed_source,
            from_date=args.from_date,
            max_listings=args.max_listings,
            write_checkpoint=not args.no_checkpoint,
        )
    except PropctrlAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
