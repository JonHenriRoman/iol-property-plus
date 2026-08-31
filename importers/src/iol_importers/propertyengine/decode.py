"""Format-agnostic front end for the PropertyEngine feed.

The Gumtree Pro "Real Estate Standard Template Feed" doc (v1.0.1) specifies JSON.
The only PropertyEngine feed anyone has actually observed is **XML** with the same
field semantics — so this module sniffs the body and normalises both shapes into
one nested-``dict`` structure the mapper can walk without caring which it was.

Everything is stdlib (``json`` + ``xml.etree.ElementTree``) — the importers
subproject deliberately carries no XML/JSON dependency beyond ``httpx``.

Two quirks the real feed forces on us, both handled here so the mapper stays clean:

* **Casing drift.** The doc capitalises ``Status``, ``City``, ``AgentID``, ``Email``;
  the real feed sends ``status``, ``CityTown``, ``AgentId``, lowercase ``email``.
  :func:`get` is case-insensitive and takes alias lists.
* **Single-or-multiple.** ``Images.Image`` and ``Agents`` decode to a dict when the
  feed carries one and a list when it carries several (XML has no array type).
  :func:`as_list` flattens both.

Absent fields stay absent (``get`` returns ``None``) — never coerced to ``0`` or
``""``. ``Bedrooms`` in particular is *removed* for a studio per the doc, and that
absence must survive to the mapper.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

_LISTINGS_KEYS = ("Listings", "listings")
_PROPERTY_KEYS = ("Property", "property")


class FeedDecodeError(ValueError):
    """The feed body is neither parseable JSON nor parseable XML, or has no root."""


def sniff_format(body: bytes | str, content_type: str | None = None) -> str:
    """Return ``"json"`` or ``"xml"`` from the first non-whitespace byte, with the
    ``Content-Type`` header as a fallback only when the body is empty/ambiguous."""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped[:1] == "{" or stripped[:1] == "[":
        return "json"
    if stripped[:1] == "<":
        return "xml"
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if "xml" in ct:
        return "xml"
    raise FeedDecodeError("feed body is neither JSON nor XML (no '{' or '<' at the start)")


def parse_feed(body: bytes | str, content_type: str | None = None) -> list[dict[str, Any]]:
    """Decode the feed and return the list of ``Property`` records as nested dicts."""
    fmt = sniff_format(body, content_type)
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    root = _parse_json(text) if fmt == "json" else _parse_xml(text)
    return _extract_properties(root)


# -- JSON --------------------------------------------------------------------


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FeedDecodeError(f"invalid JSON: {exc}") from exc


# -- XML -------------------------------------------------------------------


def _parse_xml(text: str) -> dict[str, Any]:
    try:
        element = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedDecodeError(f"invalid XML: {exc}") from exc
    return {_localname(element.tag): _element_to_obj(element)}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _element_to_obj(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        text = (element.text or "").strip()
        return text or None
    obj: dict[str, Any] = {}
    for child in children:
        name = _localname(child.tag)
        value = _element_to_obj(child)
        if name in obj:
            existing = obj[name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                obj[name] = [existing, value]
        else:
            obj[name] = value
    return obj


# -- shared -----------------------------------------------------------------


def _extract_properties(root: Any) -> list[dict[str, Any]]:
    if not isinstance(root, dict):
        raise FeedDecodeError("feed root is not an object")
    listings = _ci_get(root, _LISTINGS_KEYS)
    # XML root is <listings>, so `root` may already be the listings container.
    container = listings if isinstance(listings, dict) else root
    if not isinstance(container, dict):
        raise FeedDecodeError("no Listings object at the feed root")
    properties = _ci_get(container, _PROPERTY_KEYS)
    if properties is None:
        return []
    return [p for p in as_list(properties) if isinstance(p, dict)]


def _ci_get(mapping: dict[str, Any], names: tuple[str, ...]) -> Any:
    lowered = {k.lower(): v for k, v in mapping.items() if isinstance(k, str)}
    for name in names:
        if name in mapping:
            return mapping[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def get(record: Any, *names: str) -> Any:
    """Case-insensitive, alias-tolerant field lookup on a decoded record.

    ``get(rec, "Status")`` finds ``status``; ``get(rec, "City", "CityTown")`` finds
    either. Returns ``None`` when the field is genuinely absent — the caller must
    not treat that as ``0``.
    """
    if not isinstance(record, dict):
        return None
    return _ci_get(record, names)


def as_list(value: Any) -> list[Any]:
    """Normalise a single-or-multiple value to a list. ``None`` -> ``[]``,
    a lone dict/scalar -> ``[value]``, a list -> itself."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
