"""Adapter run — fan out over the four categories, page each fully, feed the importer."""

from __future__ import annotations

from collections.abc import Callable

import psycopg

from iol_importers.feeds.run import RunCounts
from iol_importers.listings.importer import import_listings

from .client import PropdataClient
from .map import to_import_record

CATEGORIES: tuple[str, ...] = ("residential", "commercial", "holiday", "projects")


def run(
    *,
    site_domain: str,
    feed_source_code: str,
    categories: tuple[str, ...] = CATEGORIES,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    page_limit: int | None = None,
    client: PropdataClient | None = None,
) -> dict[str, RunCounts]:
    """Import each category. One ``import_jobs`` row per category; pagination is
    followed fully before a category's job closes. Returns ``{category: RunCounts}``."""
    own_client = client is None
    client = client or PropdataClient(site_domain)
    try:
        if own_client:
            client.ensure_token()

        results: dict[str, RunCounts] = {}
        for category in categories:
            records = (
                to_import_record(raw, category=category, client=client)
                for raw in client.iter_listings(category, page_limit=page_limit)
            )
            results[category] = import_listings(
                records,
                feed_source_code=feed_source_code,
                connect=connect,
                tracking_connect=tracking_connect,
                file_reference=f"propdata:{site_domain}:{category}",
            )
        return results
    finally:
        if own_client:
            client.close()


def format_counts(results: dict[str, RunCounts]) -> str:
    lines = ["category      seen  inserted  updated  failed"]
    for category, c in results.items():
        lines.append(f"{category:<12} {c.seen:>5} {c.inserted:>9} {c.updated:>8} {c.failed:>7}")
    return "\n".join(lines)
