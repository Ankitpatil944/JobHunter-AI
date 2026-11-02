"""Tolerant feed reading. Some feeds are invalid XML, so items are parsed one at a time."""
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from email.utils import parsedate_to_datetime

BARE_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
PREFIXED_TAG = re.compile(r"<(/?)[A-Za-z_][\w.-]*:([A-Za-z_][\w.-]*)")


def _repair(block: str) -> str:
    """Escape stray entities outside CDATA, and drop namespace prefixes that may be undeclared."""
    parts = []
    last = 0
    for match in re.finditer(r"<!\[CDATA\[.*?\]\]>", block, re.S):
        parts.append(BARE_ENTITY.sub("&amp;", PREFIXED_TAG.sub(r"<\1\2", block[last:match.start()])))
        parts.append(match.group(0))
        last = match.end()
    parts.append(BARE_ENTITY.sub("&amp;", PREFIXED_TAG.sub(r"<\1\2", block[last:])))
    return "".join(parts)


def read_items(text: str, tag: str) -> Iterator[ET.Element]:
    """Yield each <tag> block that can be read, skipping any that can't."""
    for block in re.findall(rf"<{tag}\b.*?</{tag}>", text, re.S):
        try:
            yield ET.fromstring(_repair(block))
        except ET.ParseError:
            continue


def rfc822_to_iso(value: str | None) -> str | None:
    try:
        return parsedate_to_datetime(value).isoformat() if value else None
    except (TypeError, ValueError):
        return None
