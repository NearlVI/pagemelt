#!/usr/bin/env python
"""Audit or demote obvious printed-table-of-contents headings in EPUB files."""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
ET.register_namespace("", NCX_NS)

HEADING_RE = re.compile(r"<h([1-6])\b(?P<attrs>[^>]*)>(?P<body>.*?)</h\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
ID_RE = re.compile(r"""\bid\s*=\s*(['"])(?P<id>.*?)\1""", re.IGNORECASE)

PRINTED_TOC_LOCATOR_RE = re.compile(r"(?:[.\u00b7\uff0e\u3002\u2026]{2,}|/{1,2})\s*\d{1,4}\s*$")
PRINTED_TOC_BARE_PAGE_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]|"
    r"\d{1,3}[.、]\s*|"
    r"[一二三四五六七八九十]+[、.．]\s*"
    r").{2,90}\s+\d{1,4}$"
)


def normalize_text(text: str) -> str:
    text = html.unescape(TAG_RE.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def looks_like_printed_toc_entry(text: str) -> bool:
    text = normalize_text(text)
    if not text or len(text) > 120:
        return False
    return bool(PRINTED_TOC_LOCATOR_RE.search(text) or PRINTED_TOC_BARE_PAGE_RE.search(text))


def should_demote_heading(text: str) -> bool:
    return looks_like_printed_toc_entry(text)


def clean_html(data: bytes, filename: str) -> tuple[bytes, set[tuple[str, str]], set[str], int]:
    text = data.decode("utf-8", errors="replace")
    removed_ids: set[tuple[str, str]] = set()
    removed_labels: set[str] = set()
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        label = normalize_text(match.group("body"))
        if not should_demote_heading(label):
            return match.group(0)
        count += 1
        removed_labels.add(label)
        id_match = ID_RE.search(match.group("attrs") or "")
        if id_match:
            removed_ids.add((filename, html.unescape(id_match.group("id"))))
        return f"<p><strong>{html.escape(label)}</strong></p>"

    cleaned = HEADING_RE.sub(repl, text)
    if count == 0:
        return data, removed_ids, removed_labels, 0
    return cleaned.encode("utf-8"), removed_ids, removed_labels, count


def split_src(src: str) -> tuple[str, str]:
    parsed = urllib.parse.urldefrag(src)
    return urllib.parse.unquote(parsed.url), urllib.parse.unquote(parsed.fragment)


def nav_label(nav_point: ET.Element) -> str:
    label = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
    return normalize_text(label.text or "") if label is not None else ""


def nav_src(nav_point: ET.Element) -> str:
    content = nav_point.find(f"{{{NCX_NS}}}content")
    return content.attrib.get("src", "") if content is not None else ""


def renumber_navpoints(root: ET.Element) -> None:
    play_order = 1
    for nav_point in root.iter(f"{{{NCX_NS}}}navPoint"):
        nav_point.set("playOrder", str(play_order))
        play_order += 1


def clean_ncx(
    data: bytes,
    removed_ids: set[tuple[str, str]],
    removed_labels: set[str],
) -> tuple[bytes, int]:
    root = ET.fromstring(data)
    nav_map = root.find(f"{{{NCX_NS}}}navMap")
    if nav_map is None:
        return data, 0

    removed = 0

    def should_remove(nav_point: ET.Element) -> bool:
        label = nav_label(nav_point)
        file_name, fragment = split_src(nav_src(nav_point))
        if label in removed_labels or should_demote_heading(label):
            return True
        if fragment and (file_name, fragment) in removed_ids:
            return True
        return False

    def prune(parent: ET.Element) -> None:
        nonlocal removed
        for child in list(parent):
            if child.tag != f"{{{NCX_NS}}}navPoint":
                continue
            prune(child)
            if should_remove(child):
                parent.remove(child)
                removed += 1

    before = len(list(nav_map.iter(f"{{{NCX_NS}}}navPoint")))
    prune(nav_map)
    after = len(list(nav_map.iter(f"{{{NCX_NS}}}navPoint")))
    if before and after == 0:
        return data, 0
    renumber_navpoints(root)
    if removed == 0:
        return data, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), removed


def iter_epubs(paths: list[Path]) -> list[Path]:
    epubs: list[Path] = []
    for path in paths:
        if path.is_dir():
            epubs.extend(sorted(path.glob("*.epub")))
        elif path.suffix.lower() == ".epub":
            epubs.append(path)
    return epubs


def write_entry(dst: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> None:
    new_info = zipfile.ZipInfo(info.filename, info.date_time)
    new_info.comment = info.comment
    new_info.extra = info.extra
    new_info.internal_attr = info.internal_attr
    new_info.external_attr = info.external_attr
    new_info.create_system = info.create_system
    new_info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
    dst.writestr(new_info, data)


def fix_epub(path: Path, dry_run: bool) -> tuple[int, int]:
    html_changes: dict[str, bytes] = {}
    removed_ids: set[tuple[str, str]] = set()
    removed_labels: set[str] = set()
    demoted = 0

    with zipfile.ZipFile(path, "r") as src:
        infos = src.infolist()
        for info in infos:
            suffix = Path(info.filename).suffix.lower()
            if suffix in HTML_EXTENSIONS:
                data, ids, labels, count = clean_html(src.read(info.filename), info.filename)
                if count:
                    html_changes[info.filename] = data
                    removed_ids.update(ids)
                    removed_labels.update(labels)
                    demoted += count
        ncx_changes: dict[str, bytes] = {}
        removed_nav = 0
        for info in infos:
            if Path(info.filename).suffix.lower() == ".ncx":
                data, count = clean_ncx(src.read(info.filename), removed_ids, removed_labels)
                if count:
                    ncx_changes[info.filename] = data
                    removed_nav += count

    if dry_run or (not html_changes and not ncx_changes):
        return demoted, removed_nav

    fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".epub", dir=str(path.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(path, "r") as src, zipfile.ZipFile(temp_path, "w") as dst:
            infos = src.infolist()
            mimetype = next((info for info in infos if info.filename == "mimetype"), None)
            ordered = ([mimetype] if mimetype else []) + [info for info in infos if info is not mimetype]
            for info in ordered:
                data = html_changes.get(info.filename) or ncx_changes.get(info.filename) or src.read(info.filename)
                write_entry(dst, info, data)
        shutil.move(str(temp_path), str(path))
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return demoted, removed_nav


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dry_run = not args.apply

    changed = 0
    total_demoted = 0
    total_nav = 0
    for epub in iter_epubs(args.paths):
        demoted, removed_nav = fix_epub(epub, dry_run)
        if demoted or removed_nav:
            changed += 1
            total_demoted += demoted
            total_nav += removed_nav
            action = "would fix" if dry_run else "fixed"
            print(f"{epub.name}: {action}; demoted_headings={demoted}; removed_nav={removed_nav}")
    print(f"Changed EPUBs: {changed}; demoted headings: {total_demoted}; removed nav entries: {total_nav}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
