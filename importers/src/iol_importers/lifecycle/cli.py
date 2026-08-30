"""``iol-expire-listings`` — run the listing-expiry sweep.

Scheduling (nothing in this repo wires it yet — see the README's "Not yet
implemented"). Intended cadence: nightly, after the feed imports.

    # crontab
    15 2 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers iol-expire-listings >> /var/log/iol/expire.log 2>&1

Equivalents: a GitLab scheduled pipeline running the same command; a Kubernetes
CronJob with `schedule: "15 2 * * *"`; an ECS scheduled task via an EventBridge
rule.
"""

from __future__ import annotations

import argparse

from .expire import expire_listings


def _print_counts(label: str, counts: dict[str, int]) -> None:
    body = ", ".join(f"{status}={n}" for status, n in sorted(counts.items())) or "(no listings)"
    print(f"  {label}: {body}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="iol-expire-listings",
        description="Mark Active listings whose expires_at has passed as Expired.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many listings would expire without changing anything",
    )
    args = parser.parse_args(argv)

    result = expire_listings(dry_run=args.dry_run)

    verb = "would expire" if args.dry_run else "expired"
    _print_counts("before", result.status_before)
    print(f"  {verb}: {result.expired_count}")
    if not args.dry_run:
        _print_counts("after", result.status_after)
    return 0
