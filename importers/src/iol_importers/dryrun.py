"""JSON dry-run wrapper for the feed-operations web UI.

The Next.js ``/ops`` screen shells out to
``python -m iol_importers.dryrun <vendor> <feed_source_code> --json``. This module
owns the vendor -> adapter dispatch (previously only prose in the repo README)
and normalises every adapter's dry-run result to one JSON shape.

It performs **no database writes**: it calls each adapter's existing
``run(dry_run=True)``, which returns before any ``import_jobs`` row is opened. A
dry-run confirms the feed is reachable and parses, reports how many records it
carries, and surfaces the adapter's feed-shape diagnostics (unknown tags, branch
counts, and so on).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json

# vendor slug -> (adapter module, supports a dry-run mode)
_ADAPTERS: dict[str, tuple[str, bool]] = {
    "allsa": ("iol_importers.allsa.adapter", True),
    "webbox": ("iol_importers.webbox.adapter", True),
    "rt3": ("iol_importers.rt3.adapter", True),
    "myroof": ("iol_importers.myroof.adapter", True),
    "propertypost": ("iol_importers.propertypost.adapter", True),
    "entegral": ("iol_importers.entegral.adapter", True),
    "fusion": ("iol_importers.fusion.adapter", True),
    "propertyengine": ("iol_importers.propertyengine.adapter", True),
    "remax": ("iol_importers.remax.adapter", False),
    "propdata": ("iol_importers.propdata.adapter", False),
    "propctrl": ("iol_importers.propctrl.adapter", False),
}

VENDORS: tuple[str, ...] = tuple(_ADAPTERS)


class DryRunError(RuntimeError):
    """The request itself is invalid (e.g. an unknown vendor)."""


def _jsonable(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run(vendor: str, feed_source_code: str) -> dict:
    """Dry-run ``vendor`` against ``feed_source_code``; return a JSON-able dict.

    Never raises for a feed-side failure — an unreachable feed, a missing
    ``feed_sources`` row or absent credentials all come back as
    ``{"ok": False, ...}`` so the UI can show the operator what went wrong.
    """
    if vendor not in _ADAPTERS:
        raise DryRunError(f"unknown vendor {vendor!r} (known: {', '.join(VENDORS)})")

    module_path, supported = _ADAPTERS[vendor]
    base = {"vendor": vendor, "feed_source_code": feed_source_code, "supported": supported}

    if not supported:
        return {
            **base,
            "ok": False,
            "message": f"{vendor} has no dry-run mode yet — test it from the CLI instead.",
        }

    adapter = importlib.import_module(module_path)
    try:
        result = adapter.run(feed_source_code=feed_source_code, dry_run=True)
    except Exception as exc:  # noqa: BLE001 - any failure is shown to the operator
        return {
            **base,
            "ok": False,
            "error_type": type(exc).__name__,
            "message": str(exc) or type(exc).__name__,
        }

    payload = _jsonable(result)
    counts = payload.get("counts") if isinstance(payload, dict) else None
    seen = counts.get("seen") if isinstance(counts, dict) else None
    if seen is None and isinstance(payload, dict):
        seen = payload.get("seen")

    diagnostics = (
        {k: v for k, v in payload.items() if k not in {"counts", "dry_run"}}
        if isinstance(payload, dict)
        else {"result": payload}
    )

    seen_text = "the" if seen is None else str(seen)
    return {
        **base,
        "ok": True,
        "mode": "dry-run",
        "records_seen": seen,
        "diagnostics": diagnostics,
        "message": f"Reached the feed and parsed {seen_text} records — nothing was written.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m iol_importers.dryrun",
        description="Dry-run one feed and print the result as JSON. Writes nothing.",
    )
    parser.add_argument("vendor", choices=sorted(VENDORS))
    parser.add_argument("feed_source_code", help="feed_sources.code of the row to test")
    parser.add_argument(
        "--json", action="store_true", help="emit JSON (always on; accepted for clarity)"
    )
    args = parser.parse_args(argv)

    try:
        out = run(args.vendor, args.feed_source_code)
    except DryRunError as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
        return 2

    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
