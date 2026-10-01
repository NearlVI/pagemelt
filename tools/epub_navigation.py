"""Resolve NCX references and body coordinates without guessing from labels."""

from __future__ import annotations

import posixpath
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup, Tag

from audit_epub_toc_integrity import get_opf_path, OPF_NS
from build_toc_review_packets import clean_text

BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]


def resolve_href(href: str, base: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(href)
    if parts.scheme or parts.netloc or parts.query:
        raise ValueError(f"Not a local EPUB reference: {href}")
    path = urllib.parse.unquote(parts.path)
    name = posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    if name.startswith(("../", "/")) or "\\" in name:
        raise ValueError(f"Reference escapes EPUB: {href}")
    return name, urllib.parse.unquote(parts.fragment)


def ncx_name(epub: zipfile.ZipFile) -> str:
    opf = get_opf_path(epub)
    root = ET.fromstring(epub.read(opf))
    spine = root.find("opf:spine", OPF_NS)
    toc_id = spine.get("toc") if spine is not None else None
    for item in root.findall("opf:manifest/opf:item", OPF_NS):
        if (toc_id and item.get("id") == toc_id) or (
            not toc_id and item.get("media-type") == "application/x-dtbncx+xml"
        ):
            return resolve_href(item.attrib["href"], opf)[0]
    raise ValueError("EPUB package has no NCX navigation")


def content_nodes(soup: BeautifulSoup) -> list[Tag]:
    return [node for node in soup.find_all(BLOCK_TAGS) if clean_text(node.get_text(" ", strip=True))]


def target_block(soup: BeautifulSoup, nodes: list[Tag], fragment: str) -> tuple[int, Tag]:
    if not fragment:
        if not nodes:
            raise ValueError("target file has no content blocks")
        return 0, nodes[0]
    anchors = soup.find_all(id=fragment)
    if len(anchors) != 1:
        raise ValueError(f"fragment {fragment!r} has {len(anchors)} matches")
    anchor = anchors[0]
    # An id directly on a heading points to that heading, not the following paragraph.
    candidates = [anchor, anchor.find_parent(BLOCK_TAGS), anchor.find_next(BLOCK_TAGS)]
    positions = {id(node): index for index, node in enumerate(nodes)}
    for candidate in candidates:
        if candidate is not None and id(candidate) in positions:
            return positions[id(candidate)], candidate
    raise ValueError(f"fragment {fragment!r} has no content block")
