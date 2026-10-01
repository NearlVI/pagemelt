#!/usr/bin/env python
"""Add reviewed top-level TOC entries at the start or end of an existing NCX."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from apply_epub_toc_coordinates import (
    NCX,
    NCX_NS,
    blocks,
    clean,
    insert_before_block,
    ncx_name,
    write_zip_entry,
)


ET.register_namespace("", NCX_NS)


def find_book(input_dir: Path, pattern: str) -> Path:
    exact = input_dir / pattern
    if exact.is_file():
        return exact
    matches = [path for path in input_dir.glob("*.epub") if fnmatch.fnmatch(path.name, pattern)]
    if len(matches) != 1:
        raise ValueError(f"Pattern {pattern!r} matched {len(matches)} EPUBs")
    return matches[0]


def validate(path: Path, additions: list[dict[str, Any]]) -> list[str]:
    evidence: list[str] = []
    with zipfile.ZipFile(path) as epub:
        names = set(epub.namelist())
        root = ET.fromstring(epub.read(ncx_name(epub)))
        existing_labels = {
            clean(node.text or "") for node in root.findall(".//n:navLabel/n:text", NCX)
        }
        for index, addition in enumerate(additions, 1):
            position = addition["position"]
            if position not in {"start", "end"}:
                raise ValueError(f"{path.name}: invalid position {position!r}")
            label = clean(addition["label"])
            if label in existing_labels:
                raise ValueError(f"{path.name}: TOC already contains {label!r}")
            file_name = addition["file"]
            block_index = int(addition["block"])
            if file_name not in names:
                raise ValueError(f"{path.name}: missing {file_name}")
            book_blocks = blocks(epub.read(file_name))
            if not 0 <= block_index < len(book_blocks):
                raise ValueError(
                    f"{path.name}: {file_name} block {block_index} outside 0..{len(book_blocks)-1}"
                )
            tag, target = book_blocks[block_index]
            expect = clean(addition.get("expect", ""))
            if expect and expect not in target:
                raise ValueError(
                    f"{path.name}: expected {expect!r} at {file_name}#{block_index}, got {target!r}"
                )
            evidence.append(
                f"{index:03d} | {position} | {label} | {file_name}#{block_index} <{tag}> | {target[:180]}"
            )
    return evidence


def make_nav_point(identifier: str, label: str, src: str) -> ET.Element:
    point = ET.Element(f"{{{NCX_NS}}}navPoint", {"id": identifier})
    nav_label = ET.SubElement(point, f"{{{NCX_NS}}}navLabel")
    text = ET.SubElement(nav_label, f"{{{NCX_NS}}}text")
    text.text = label
    ET.SubElement(point, f"{{{NCX_NS}}}content", {"src": src})
    return point


def apply_one(path: Path, additions: list[dict[str, Any]]) -> None:
    validate(path, additions)
    with zipfile.ZipFile(path, "r") as source:
        infos = source.infolist()
        nav_name = ncx_name(source)
        root = ET.fromstring(source.read(nav_name))
        nav_map = root.find("n:navMap", NCX)
        if nav_map is None:
            raise ValueError(f"{path.name}: NCX has no navMap")

        existing_ids = {node.attrib.get("id", "") for node in root.findall(".//n:navPoint", NCX)}
        updates: dict[str, bytes] = {}
        prepared: list[tuple[dict[str, Any], str]] = []
        next_number = 1
        for addition in additions:
            while f"manual_extra_{next_number}" in existing_ids:
                next_number += 1
            anchor_id = f"manual_extra_{next_number}"
            next_number += 1
            existing_ids.add(anchor_id)
            prepared.append((addition, anchor_id))

        by_file: dict[str, list[tuple[dict[str, Any], str]]] = {}
        for addition, anchor_id in prepared:
            by_file.setdefault(addition["file"], []).append((addition, anchor_id))
        for file_name, items in by_file.items():
            raw = source.read(file_name)
            for addition, anchor_id in sorted(items, key=lambda item: int(item[0]["block"]), reverse=True):
                raw = insert_before_block(raw, int(addition["block"]), anchor_id)
            updates[file_name] = raw

        starts = [item for item in prepared if item[0]["position"] == "start"]
        ends = [item for item in prepared if item[0]["position"] == "end"]
        insert_at = 0
        for addition, anchor_id in starts:
            point = make_nav_point(
                anchor_id,
                addition["label"],
                f"{addition['file']}#{anchor_id}",
            )
            nav_map.insert(insert_at, point)
            insert_at += 1
        for addition, anchor_id in ends:
            nav_map.append(
                make_nav_point(
                    anchor_id,
                    addition["label"],
                    f"{addition['file']}#{anchor_id}",
                )
            )

        for play_order, point in enumerate(root.findall(".//n:navPoint", NCX), 1):
            point.attrib["playOrder"] = str(play_order)
        updates[nav_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".epub", dir=path.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            with zipfile.ZipFile(temp, "w") as target:
                for info in infos:
                    write_zip_entry(target, info, updates.get(info.filename, source.read(info.filename)))
            with zipfile.ZipFile(temp) as check:
                bad = check.testzip()
                if bad:
                    raise ValueError(f"{path.name}: bad ZIP member after update: {bad}")
            source.close()
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.apply and args.backup_dir is None:
        parser.error("--backup-dir is required with --apply")
    data = json.loads(args.spec.read_text(encoding="utf-8"))
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)

    resolved: list[tuple[Path, list[dict[str, Any]]]] = []
    for book in data["books"]:
        path = find_book(args.input_dir, book["file"])
        evidence = validate(path, book["additions"])
        (args.evidence_dir / f"{path.stem}.txt").write_text("\n".join(evidence) + "\n", encoding="utf-8")
        print(f"VALID {path.name}: {len(evidence)} additions")
        resolved.append((path, book["additions"]))

    if not args.apply:
        print("Dry run only; no EPUB files changed")
        return 0

    for path, additions in resolved:
        shutil.copy2(path, args.backup_dir / path.name)
        apply_one(path, additions)
        print(f"APPLIED {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
