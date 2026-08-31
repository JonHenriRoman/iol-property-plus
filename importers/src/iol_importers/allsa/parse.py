"""Parse an AllSA ``iol.ashx`` document into :class:`Property` records.

Stdlib ``xml.etree.ElementTree`` — no lxml/defusedxml (no new tooling; a trusted
vendor over TLS, same call :mod:`iol_importers.fusion` makes; see ``MAPPING_NOTES``).

Structure (confirmed against the real ``agencyid=10173`` feed, 1230 properties):

    <Listings>
      <Property>
        <Reference>1604015</Reference>
        ... 22 more scalar tags ...
        <Images><Image>https://.../a.jpg</Image>...</Images>
        <Features><Floor_Size>124</Floor_Size><Levies>645</Levies>...</Features>
      </Property>
    </Listings>

Two real-world hazards this handles:

* ``<Listings />`` (empty) — a valid response for an unknown agencyid. Returns
  ``[]``; the adapter refuses to reconcile on an empty pull.
* ``<Features>`` children **repeat within one Property** — listing 2509202 in the
  real feed carries each of its 10 feature tags 1852 times. First occurrence per
  tag wins; the drop count is returned so a feed regression is visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, ParseError, fromstring


class AllsaParseError(RuntimeError):
    """The body is not a well-formed ``<Listings>`` document."""


@dataclass(frozen=True, slots=True)
class Property:
    fields: dict[str, str]
    images: tuple[str, ...]
    features: tuple[tuple[str, str], ...]
    duplicate_feature_elements: int = 0


@dataclass
class ParseResult:
    properties: list[Property] = field(default_factory=list)
    duplicate_feature_elements: int = 0


def _text(element: Element) -> str:
    return (element.text or "").strip()


def _parse_features(node: Element) -> tuple[tuple[tuple[str, str], ...], int]:
    seen: dict[str, str] = {}
    dropped = 0
    for child in node:
        tag = child.tag
        if tag in seen:
            dropped += 1
            continue
        seen[tag] = _text(child)
    return tuple(seen.items()), dropped


def _parse_property(node: Element) -> Property:
    fields: dict[str, str] = {}
    images: list[str] = []
    features: tuple[tuple[str, str], ...] = ()
    dropped = 0
    for child in node:
        if child.tag == "Images":
            images = [_text(img) for img in child if _text(img)]
        elif child.tag == "Features":
            features, dropped = _parse_features(child)
        else:
            fields[child.tag] = _text(child)
    return Property(
        fields=fields,
        images=tuple(images),
        features=features,
        duplicate_feature_elements=dropped,
    )


def parse_feed(body: bytes | str) -> ParseResult:
    """``bytes``/``str`` -> :class:`ParseResult`. Raises :class:`AllsaParseError`
    on a malformed body or a wrong root tag. ``<Listings />`` -> empty result."""
    try:
        root = fromstring(body)
    except ParseError as exc:
        raise AllsaParseError(f"not well-formed XML: {exc}") from exc

    if root.tag != "Listings":
        raise AllsaParseError(f"root tag is <{root.tag}>, expected <Listings>")

    result = ParseResult()
    for node in root:
        if node.tag != "Property":
            continue
        prop = _parse_property(node)
        result.properties.append(prop)
        result.duplicate_feature_elements += prop.duplicate_feature_elements
    return result
