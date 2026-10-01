#!/usr/bin/env python
"""Strict, failure-producing acceptance checks for an EPUB TOC corpus."""

from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from audit_epub_toc_integrity import html_spine
from build_toc_review_packets import clean_text
from export_epub_toc_coordinates import export_book
from epub_navigation import ncx_name, content_nodes, resolve_href, target_block
from apply_epub_toc_coordinates import validate_spec


NCX = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]
TEXT_PREFIX_RE = re.compile(r"^\s*text(?:\s*[-:：]|\s+)", re.IGNORECASE)
PAGE_SUFFIX_RE = re.compile(r"(?:[/／]{1,2}|[.．…_]{2,})\s*[（(]?\d{1,4}[）)]?\s*$")
BARE_PAGE_RE = re.compile(r"^\s*\d{2,4}\s*$")
TOC_LABEL_RE = re.compile(r"^(?:目录|目次|contents?|table of contents)$", re.IGNORECASE)


def compact_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for entry in entries:
        item = {
            "label": entry["label"],
            "file": entry["file"],
            "block": int(entry["block"]),
        }
        children = compact_entries(entry.get("children") or [])
        if children:
            item["children"] = children
        result.append(item)
    return result


def expected_specs(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    books = data["books"]
    if not books or len({book["file"] for book in books}) != len(books):
        raise ValueError("Accepted spec must contain books with unique filenames")
    return {book["file"]: book["entries"] for book in books}


def validate_book(path: Path) -> tuple[int, list[str]]:
    try:
        return _validate_book(path)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, RuntimeError) as exc:
        return 0, [f"Unreadable EPUB: {exc}"]


def _validate_book(path: Path) -> tuple[int, list[str]]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as epub:
        corrupt = epub.testzip()
        if corrupt:
            errors.append(f"corrupt ZIP member: {corrupt}")
        infos = epub.infolist()
        if not infos or infos[0].filename != "mimetype":
            errors.append("mimetype is not the first ZIP member")
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            errors.append("mimetype is compressed")
        if epub.read("mimetype") != b"application/epub+zip":
            errors.append("invalid mimetype content")
        if len(set(epub.namelist())) != len(infos):
            errors.append("duplicate ZIP member names")

        ncx_file = ncx_name(epub)
        try:
            root = ET.fromstring(epub.read(ncx_file))
        except ET.ParseError as exc:
            return 0, errors + [f"invalid NCX XML: {exc}"]

        points = root.findall(".//n:navPoint", NCX)
        if not points:
            errors.append("empty NCX navigation")
        spine = html_spine(epub)
        spine_index = {name: index for index, name in enumerate(spine)}
        soup_cache: dict[str, BeautifulSoup] = {}
        nodes_cache: dict[str, list[Tag]] = {}
        targets: list[tuple[str, int]] = []
        positions: list[tuple[int, int]] = []
        play_orders: list[int] = []

        for index, point in enumerate(points, 1):
            label_node = point.find("n:navLabel/n:text", NCX)
            content = point.find("n:content", NCX)
            label = clean_text(label_node.text or "") if label_node is not None else ""
            src = content.attrib.get("src", "") if content is not None else ""
            if not label:
                errors.append(f"item {index}: empty label")
            if TEXT_PREFIX_RE.search(label):
                errors.append(f"item {index}: text prefix in label: {label}")
            if PAGE_SUFFIX_RE.search(label) or BARE_PAGE_RE.fullmatch(label):
                errors.append(f"item {index}: page locator in label: {label}")
            if TOC_LABEL_RE.fullmatch(label):
                errors.append(f"item {index}: printed contents page exposed as navigation")

            play_order = point.attrib.get("playOrder", "")
            if not play_order.isdigit():
                errors.append(f"item {index}: invalid playOrder: {play_order!r}")
            else:
                play_orders.append(int(play_order))

            try:
                file_name, fragment = resolve_href(src, ncx_file)
            except ValueError as exc:
                errors.append(f"item {index}: {exc}")
                continue
            if file_name not in epub.namelist() or file_name not in spine_index:
                errors.append(f"item {index}: missing target file: {src}")
                continue
            if file_name not in soup_cache:
                soup_cache[file_name] = BeautifulSoup(epub.read(file_name), "lxml")
                nodes_cache[file_name] = content_nodes(soup_cache[file_name])
            soup = soup_cache[file_name]
            nodes = nodes_cache[file_name]
            try:
                block, target = target_block(soup, nodes, fragment)
            except ValueError as exc:
                errors.append(f"item {index}: {src}: {exc}")
                continue
            target_text = clean_text(target.get_text(" ", strip=True))
            if PAGE_SUFFIX_RE.search(target_text):
                errors.append(f"item {index}: target is a printed-TOC locator: {target_text[:100]}")
            targets.append((file_name, block))
            positions.append((spine_index[file_name], block))

        expected_orders = list(range(1, len(points) + 1))
        if play_orders != expected_orders:
            errors.append("playOrder values are not the exact 1..N sequence")
        duplicates = [src for src, count in Counter(targets).items() if count > 1]
        if duplicates:
            errors.append(f"shared navigation targets: {duplicates[:3]}")
        if any(right < left for left, right in zip(positions, positions[1:])):
            errors.append("navigation targets are not in body reading order")
    return len(points), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub_dir", type=Path)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()

    paths = sorted(args.epub_dir.glob("*.epub"))
    if not paths:
        raise ValueError(f"No EPUB files found in {args.epub_dir}")
    expected = expected_specs(args.spec)
    rows = []
    for path in paths:
        nav_items, errors = validate_book(path)
        if args.spec is not None:
            if path.name not in expected:
                errors.append("book is not present in the accepted spec")
            else:
                try:
                    actual = compact_entries(export_book(path)["entries"])
                    if actual != compact_entries(expected[path.name]):
                        errors.append("TOC hierarchy or target coordinates differ from the accepted spec")
                    validate_spec(path, {"entries": expected[path.name]})
                except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, RuntimeError) as exc:
                    errors.append(f"Spec verification failed: {exc}")
        rows.append({
            "name": path.name,
            "nav_items": nav_items,
            "status": "pass" if not errors else "fail",
            "errors": " | ".join(errors),
        })
    if expected:
        missing = sorted(set(expected) - {path.name for path in paths})
        rows.extend({"name": name, "nav_items": 0, "status": "fail", "errors": "book is missing"} for name in missing)

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "nav_items", "status", "errors"])
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if row["status"] == "fail"]
    print(f"EPUB files: {len(paths)}")
    print(f"Navigation items: {sum(int(row['nav_items']) for row in rows)}")
    print(f"Acceptance failures: {len(failures)}")
    for row in failures[:30]:
        print(f"FAIL {row['name']}: {row['errors']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
