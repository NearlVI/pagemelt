#!/usr/bin/env python
"""Move reviewed top-level NCX entries before another top-level entry."""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
NS = {"n": NCX_NS}


def label_of(point: ET.Element) -> str:
    node = point.find("n:navLabel/n:text", NS)
    return (node.text or "").strip() if node is not None else ""


def resolve_book(directory: Path, pattern: str) -> Path:
    exact = directory / pattern
    if exact.is_file():
        return exact
    matches = [path for path in directory.glob("*.epub") if fnmatch.fnmatch(path.name, pattern)]
    if len(matches) != 1:
        raise ValueError(f"Expected one match for {pattern!r}, found {len(matches)}")
    return matches[0]


def move_entries(path: Path, labels: list[str], before: str, backup_dir: Path) -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub", dir=path.parent) as handle:
        temp_path = Path(handle.name)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / path.name
    if not backup.exists():
        backup.write_bytes(path.read_bytes())

    with zipfile.ZipFile(path, "r") as source:
        names = source.namelist()
        ncx_name = next((name for name in names if name.lower().endswith(".ncx")), None)
        if not ncx_name:
            raise ValueError(f"No NCX in {path.name}")
        root = ET.fromstring(source.read(ncx_name))
        nav_map = root.find("n:navMap", NS)
        if nav_map is None:
            raise ValueError(f"No navMap in {path.name}")

        points = list(nav_map.findall("n:navPoint", NS))
        by_label = {label_of(point): point for point in points}
        if len(by_label) != len(points):
            raise ValueError(f"Duplicate top-level labels in {path.name}")
        missing = [label for label in [*labels, before] if label not in by_label]
        if missing:
            raise ValueError(f"Missing labels in {path.name}: {missing}")

        moving = [by_label[label] for label in labels]
        for point in moving:
            nav_map.remove(point)
        insert_at = list(nav_map).index(by_label[before])
        for offset, point in enumerate(moving):
            nav_map.insert(insert_at + offset, point)

        for order, point in enumerate(root.findall(".//n:navPoint", NS), 1):
            point.set("playOrder", str(order))
        updated_ncx = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(temp_path, "w") as target:
            for item in source.infolist():
                payload = updated_ncx if item.filename == ncx_name else source.read(item.filename)
                target.writestr(copy.copy(item), payload)

    try:
        with zipfile.ZipFile(temp_path, "r") as check:
            if check.testzip() is not None:
                raise ValueError(f"ZIP validation failed for {path.name}")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epub-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.spec.read_text(encoding="utf-8"))
    for book in data["books"]:
        path = resolve_book(args.epub_dir, book["file"])
        move_entries(path, book["labels"], book["before"], args.backup_dir)
        print(f"Updated {path.name}: moved {len(book['labels'])} entries before {book['before']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
