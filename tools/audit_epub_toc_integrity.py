#!/usr/bin/env python
"""Audit EPUB NCX targets for printed-TOC anchors and ordering problems."""

from __future__ import annotations

import argparse
import csv
import html
import posixpath
import re
import urllib.parse
import warnings
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}

TAG_RE = re.compile(r"<[^>]+>")
PAGE_LOCATOR_RE = re.compile(r"(?:[.\u00b7\uff0e\u3002\u2026_]{2,}|/{1,2})\s*\d{1,4}")
LEADING_PAGE_RE = re.compile(r"(?:^|\s)\d{1,4}\s+[\u4e00-\u9fffA-Za-z]")
ID_RE_TEMPLATE = r"\bid\s*=\s*['\"]{}['\"]"
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]


@dataclass
class NavTarget:
    label: str
    src: str
    file_name: str
    fragment: str
    file_index: int
    offset: int
    position: int
    snippet: str
    printed_like: bool


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text))).strip()


def decode_href(href: str, base: str = "") -> str:
    href = urllib.parse.unquote(href)
    if base:
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    return href


def split_src(src: str) -> tuple[str, str]:
    base, frag = urllib.parse.urldefrag(src)
    return urllib.parse.unquote(base), urllib.parse.unquote(frag)


def get_opf_path(epub: zipfile.ZipFile) -> str:
    root = ET.fromstring(epub.read("META-INF/container.xml"))
    rootfile = root.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is not None:
        return rootfile.attrib["full-path"]
    for name in epub.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ValueError("No OPF file found")


def html_spine(epub: zipfile.ZipFile) -> list[str]:
    opf_path = get_opf_path(epub)
    opf_root = ET.fromstring(epub.read(opf_path))
    manifest: dict[str, str] = {}
    for item in opf_root.findall(".//opf:manifest/opf:item", OPF_NS):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = decode_href(href, opf_path)

    ordered: list[str] = []
    for itemref in opf_root.findall(".//opf:spine/opf:itemref", OPF_NS):
        href = manifest.get(itemref.attrib.get("idref", ""))
        if href and Path(href).suffix.lower() in HTML_EXTENSIONS:
            ordered.append(href)
    return ordered


def ncx_name(epub: zipfile.ZipFile) -> str | None:
    return next((name for name in epub.namelist() if name.lower().endswith(".ncx")), None)


def nav_label(nav_point: ET.Element) -> str:
    label = nav_point.find("n:navLabel/n:text", NCX_NS)
    return normalize_text(label.text or "") if label is not None else ""


def nav_src(nav_point: ET.Element) -> str:
    content = nav_point.find("n:content", NCX_NS)
    return content.attrib.get("src", "") if content is not None else ""


def find_fragment_offset(text: str, fragment: str, label: str) -> int:
    if fragment:
        match = re.search(ID_RE_TEMPLATE.format(re.escape(fragment)), text)
        return match.start() if match else -1
    if label:
        idx = normalize_text(text).find(label)
        if idx >= 0:
            return idx
    return 0


def anchor_snippet(text: str, offset: int) -> str:
    return normalize_text(text[max(0, offset - 500) : offset + 900])


def looks_like_printed_toc_target(snippet: str) -> bool:
    head = snippet[:700]
    locator_count = len(PAGE_LOCATOR_RE.findall(head))
    leading_page_count = len(LEADING_PAGE_RE.findall(head))
    has_toc_word = "目录" in head or "Contents" in head
    if has_toc_word and (locator_count >= 1 or leading_page_count >= 3):
        return True
    if locator_count >= 2:
        return True
    if "/" in head and locator_count >= 1:
        return True
    return False


def extract_targets(path: Path) -> list[NavTarget]:
    with zipfile.ZipFile(path) as epub:
        spine = html_spine(epub)
        spine_index = {name: index for index, name in enumerate(spine)}
        html_text = {
            name: epub.read(name).decode("utf-8", errors="replace")
            for name in spine
            if name in epub.namelist()
        }
        soup_cache: dict[str, BeautifulSoup] = {}
        ncx = ncx_name(epub)
        if not ncx:
            return []
        root = ET.fromstring(epub.read(ncx))
        targets: list[NavTarget] = []
        for nav_point in root.findall(".//n:navPoint", NCX_NS):
            label = nav_label(nav_point)
            src = nav_src(nav_point)
            file_name, fragment = split_src(src)
            file_index = spine_index.get(file_name, -1)
            text = html_text.get(file_name, "")
            offset = find_fragment_offset(text, fragment, label) if text else -1
            position = file_index * 1_000_000_000 + max(offset, 0) if file_index >= 0 else -1
            snippet = anchor_snippet(text, max(offset, 0)) if text else ""
            target_text = ""
            if text and offset >= 0:
                if file_name not in soup_cache:
                    soup_cache[file_name] = BeautifulSoup(text, "lxml")
                soup = soup_cache[file_name]
                nodes = [
                    node for node in soup.find_all(BLOCK_TAGS)
                    if normalize_text(node.get_text(" ", strip=True))
                ]
                target: Tag | None = None
                if fragment:
                    anchor = soup.find(id=fragment)
                    if anchor is not None:
                        parent = anchor.find_parent(BLOCK_TAGS)
                        target = parent if isinstance(parent, Tag) and parent in nodes else anchor.find_next(BLOCK_TAGS)
                elif nodes:
                    target = nodes[0]
                if isinstance(target, Tag):
                    target_text = normalize_text(target.get_text(" ", strip=True))
            targets.append(
                NavTarget(
                    label=label,
                    src=src,
                    file_name=file_name,
                    fragment=fragment,
                    file_index=file_index,
                    offset=offset,
                    position=position,
                    snippet=snippet,
                    printed_like=looks_like_printed_toc_target(target_text),
                )
            )
    return targets


def audit_epub(path: Path) -> dict[str, object]:
    targets = extract_targets(path)
    inversions = 0
    largest_backtrack = 0
    previous = -1
    for target in targets:
        if target.position >= 0 and previous >= 0 and target.position < previous:
            inversions += 1
            largest_backtrack = max(largest_backtrack, previous - target.position)
        if target.position >= 0:
            previous = max(previous, target.position)

    printed_targets = [target for target in targets if target.printed_like]
    missing_targets = [target for target in targets if target.file_index < 0 or target.offset < 0]
    first_bad = printed_targets[0] if printed_targets else None
    first_inversion = ""
    previous_target: NavTarget | None = None
    max_seen: NavTarget | None = None
    for target in targets:
        if target.position < 0:
            continue
        if max_seen is not None and target.position < max_seen.position:
            previous_target = max_seen
            first_inversion = f"{previous_target.label} -> {target.label}"
            break
        if max_seen is None or target.position > max_seen.position:
            max_seen = target

    return {
        "name": path.name,
        "nav_items": len(targets),
        "printed_toc_targets": len(printed_targets),
        "order_inversions": inversions,
        "missing_targets": len(missing_targets),
        "largest_backtrack": largest_backtrack,
        "first_printed_label": first_bad.label if first_bad else "",
        "first_printed_src": first_bad.src if first_bad else "",
        "first_printed_near": first_bad.snippet[:220] if first_bad else "",
        "first_inversion": first_inversion,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epub-dir", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    args = parser.parse_args()

    rows = [audit_epub(path) for path in sorted(args.epub_dir.glob("*.epub"))]
    fields = [
        "name",
        "nav_items",
        "printed_toc_targets",
        "order_inversions",
        "missing_targets",
        "largest_backtrack",
        "first_printed_label",
        "first_printed_src",
        "first_printed_near",
        "first_inversion",
    ]
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    suspicious = [
        row
        for row in rows
        if int(row["printed_toc_targets"]) or int(row["order_inversions"]) or int(row["missing_targets"])
    ]
    print(f"EPUB files: {len(rows)}")
    print(f"Suspicious TOCs: {len(suspicious)}")
    print(f"Printed-TOC targets: {sum(int(row['printed_toc_targets']) for row in rows)}")
    print(f"Order inversions: {sum(int(row['order_inversions']) for row in rows)}")
    print(f"Missing targets: {sum(int(row['missing_targets']) for row in rows)}")
    for row in sorted(
        suspicious,
        key=lambda item: (
            -int(item["printed_toc_targets"]),
            -int(item["order_inversions"]),
            item["name"],
        ),
    )[:30]:
        print(
            f"{row['printed_toc_targets']:>3} printed | "
            f"{row['order_inversions']:>3} inversions | "
            f"{row['missing_targets']:>2} missing | {row['name']}"
        )
        if row["first_printed_label"]:
            print(f"    printed: {row['first_printed_label']} -> {row['first_printed_src']}")
        if row["first_inversion"]:
            print(f"    inversion: {row['first_inversion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
