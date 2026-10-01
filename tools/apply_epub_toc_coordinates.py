#!/usr/bin/env python
"""Apply reviewed EPUB TOCs using exact source block coordinates."""

from __future__ import annotations

import argparse
import fnmatch
import html
import json
import os
import posixpath
import re
import shutil
import tempfile
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from epub_navigation import ncx_name
from audit_epub_toc_integrity import html_spine
import warnings


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
NCX = {"n": NCX_NS}
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"}
ANCHOR_RE = re.compile(r"<a\b[^>]*\bid=['\"]manual_toc_\d+['\"][^>]*>\s*</a>", re.I)
SPACE_RE = re.compile(r"\s+")
ET.register_namespace("", NCX_NS)


def clean(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(value)).strip()


def text_fingerprint(value: str) -> str:
    return SPACE_RE.sub("", clean(value))


def blocks(raw: bytes) -> list[tuple[str, str]]:
    soup = BeautifulSoup(raw, "lxml")
    return [
        (node.name.lower(), clean(node.get_text(" ", strip=True)))
        for node in soup.find_all(list(BLOCK_TAGS))
        if clean(node.get_text(" ", strip=True))
    ]


def insert_anchors(
    raw: bytes,
    assignments: list[tuple[int, str]],
    *,
    remove_existing: bool = False,
) -> bytes:
    soup = BeautifulSoup(raw, "lxml")
    if remove_existing:
        for anchor in soup.find_all("a", id=re.compile(r"^manual_toc_\d+$", re.I)):
            anchor.unwrap() if clean(anchor.get_text(" ", strip=True)) else anchor.decompose()
    nodes = [
        node
        for node in soup.find_all(list(BLOCK_TAGS))
        if clean(node.get_text(" ", strip=True))
    ]
    for block_index, anchor_id in reversed(assignments):
        if not 0 <= block_index < len(nodes):
            raise IndexError(
                f"Block index {block_index} not found; only {len(nodes)} non-empty blocks"
            )
        nodes[block_index].insert(0, soup.new_tag("a", id=anchor_id))
    return soup.encode("utf-8", formatter="minimal")


def insert_before_block(raw: bytes, block_index: int, anchor_id: str) -> bytes:
    return insert_anchors(raw, [(block_index, anchor_id)])


def remove_old_anchors(raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="replace")
    return ANCHOR_RE.sub("", text).encode("utf-8")


def flatten(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in entries:
        result.append(entry)
        result.extend(flatten(entry.get("children") or []))
    return result


def build_nav(entries: list[dict[str, Any]]) -> ET.Element:
    nav_map = ET.Element(f"{{{NCX_NS}}}navMap")
    counter = [1]

    def add(parent: ET.Element, items: list[dict[str, Any]]) -> None:
        for item in items:
            number = counter[0]
            counter[0] += 1
            point = ET.SubElement(
                parent,
                f"{{{NCX_NS}}}navPoint",
                {"id": f"manual_toc_{number}", "playOrder": str(number)},
            )
            label = ET.SubElement(point, f"{{{NCX_NS}}}navLabel")
            text = ET.SubElement(label, f"{{{NCX_NS}}}text")
            text.text = item["label"]
            ET.SubElement(point, f"{{{NCX_NS}}}content", {"src": item["src"]})
            add(point, item.get("children") or [])

    add(nav_map, entries)
    return nav_map


def replace_nav(raw: bytes, entries: list[dict[str, Any]]) -> bytes:
    root = ET.fromstring(raw)
    old = root.find("n:navMap", NCX)
    if old is not None:
        parent = root
        index = list(parent).index(old)
        parent.remove(old)
        parent.insert(index, build_nav(entries))
    else:
        root.append(build_nav(entries))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_zip_entry(dst: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> None:
    clone = zipfile.ZipInfo(info.filename, info.date_time)
    clone.comment = info.comment
    clone.extra = info.extra
    clone.internal_attr = info.internal_attr
    clone.external_attr = info.external_attr
    clone.create_system = info.create_system
    clone.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
    dst.writestr(clone, data)


def validate_spec(epub_path: Path, spec: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    with zipfile.ZipFile(epub_path) as epub:
        names = set(epub.namelist())
        spine_order = {name: index for index, name in enumerate(html_spine(epub))}
        spine_files = set(spine_order)
        navigation = ncx_name(epub)
        cache: dict[str, list[tuple[str, str]]] = {}
        seen: set[tuple[str, int]] = set()
        previous_position = (-1, -1)
        if not spec["entries"]:
            raise ValueError(f"{epub_path.name}: empty TOC specification")
        for number, entry in enumerate(flatten(spec["entries"]), 1):
            file_name = entry["file"]
            block_index = int(entry["block"])
            if file_name not in names or file_name not in spine_files:
                raise ValueError(f"{epub_path.name}: missing spine file {file_name}")
            coordinate = (file_name, block_index)
            position = (spine_order[file_name], block_index)
            if coordinate in seen:
                raise ValueError(f"{epub_path.name}: shared target block {coordinate}")
            if position < previous_position:
                raise ValueError(f"{epub_path.name}: targets are not in body reading order at item {number}")
            if not clean(entry.get("label", "")):
                raise ValueError(f"{epub_path.name}: empty label at item {number}")
            seen.add(coordinate)
            previous_position = position
            if file_name not in cache:
                cache[file_name] = blocks(epub.read(file_name))
            book_blocks = cache[file_name]
            if not 0 <= block_index < len(book_blocks):
                raise ValueError(
                    f"{epub_path.name}: {file_name} block {block_index} outside 0..{len(book_blocks)-1}"
                )
            tag, target = book_blocks[block_index]
            expect = clean(entry.get("expect", ""))
            if not expect:
                raise ValueError(f"{epub_path.name}: item {number} requires expect text")
            if text_fingerprint(expect) not in text_fingerprint(target):
                raise ValueError(
                    f"{epub_path.name}: expected {expect!r} at {file_name}#{block_index}, got {target!r}"
                )
            relative = posixpath.relpath(file_name, posixpath.dirname(navigation) or ".")
            entry["src"] = f"{urllib.parse.quote(relative)}#manual_toc_{number}"
            evidence.append(
                f"{number:03d} | {entry['label']} | {file_name}#{block_index} <{tag}> | {target[:180]}"
            )
        ncx_name(epub)
    return evidence


def apply_one(epub_path: Path, spec: dict[str, Any]) -> None:
    validate_spec(epub_path, spec)
    flat = flatten(spec["entries"])
    with zipfile.ZipFile(epub_path, "r") as src:
        infos = src.infolist()
        updates: dict[str, bytes] = {}
        html_names = {
            info.filename
            for info in infos
            if Path(info.filename).suffix.lower() in {".html", ".xhtml", ".htm"}
        }
        assignments: dict[str, list[tuple[int, str]]] = {}
        for number, entry in enumerate(flat, 1):
            name = entry["file"]
            assignments.setdefault(name, []).append((int(entry["block"]), f"manual_toc_{number}"))
        for name in html_names:
            raw = src.read(name)
            if name in assignments or b"manual_toc_" in raw.lower():
                updates[name] = insert_anchors(
                    raw,
                    assignments.get(name, []),
                    remove_existing=True,
                )
        nav_name = ncx_name(src)
        updates[nav_name] = replace_nav(src.read(nav_name), spec["entries"])

        fd, temp_name = tempfile.mkstemp(prefix=epub_path.stem + ".", suffix=".epub", dir=epub_path.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            with zipfile.ZipFile(temp, "w") as dst:
                for info in infos:
                    write_zip_entry(dst, info, updates.get(info.filename, src.read(info.filename)))
            with zipfile.ZipFile(temp) as check:
                bad = check.testzip()
                if bad:
                    raise ValueError(f"Bad zip member after rebuild: {bad}")
            # Windows will not replace an EPUB while its source ZIP handle is open.
            src.close()
            os.replace(temp, epub_path)
        finally:
            if temp.exists():
                temp.unlink()


def find_book(input_dir: Path, pattern: str) -> Path:
    exact = input_dir / pattern
    if exact.is_file():
        return exact
    matches = [p for p in input_dir.glob("*.epub") if fnmatch.fnmatch(p.name, pattern)]
    if len(matches) != 1:
        raise ValueError(f"Pattern {pattern!r} matched {len(matches)} EPUBs")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()

    if args.apply and args.backup_dir is None:
        parser.error("--backup-dir is required with --apply")
    if args.apply and args.backup_dir.resolve().is_relative_to(args.input_dir.resolve()):
        parser.error("--backup-dir must be outside the EPUB input directory")

    data = json.loads(args.spec.read_text(encoding="utf-8"))
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    resolved: list[tuple[Path, dict[str, Any], list[str]]] = []
    for spec in data["books"]:
        path = find_book(args.input_dir, spec["file"])
        evidence = validate_spec(path, spec)
        resolved.append((path, spec, evidence))
        (args.evidence_dir / f"{path.stem}.txt").write_text("\n".join(evidence) + "\n", encoding="utf-8")
        print(f"VALID {path.name}: {len(evidence)} entries")

    if not args.apply:
        print("Dry run only; no EPUB files changed")
        return 0

    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        conflicts = [path.name for path, _, _ in resolved if (args.backup_dir / path.name).exists()]
        if conflicts:
            raise FileExistsError(
                f"Backup directory already contains {len(conflicts)} target EPUB(s): "
                f"{conflicts[:3]}"
            )
        for path, _, _ in resolved:
            shutil.copy2(path, args.backup_dir / path.name)
    for path, spec, _ in resolved:
        apply_one(path, spec)
        print(f"APPLIED {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
