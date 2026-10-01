#!/usr/bin/env python
"""Apply reviewed NCX label-only corrections without changing TOC targets."""

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


NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
NS = {"n": NCX_NS}
ET.register_namespace("", NCX_NS)


def find_book(input_dir: Path, pattern: str) -> Path:
    exact = input_dir / pattern
    if exact.is_file():
        return exact
    matches = [path for path in input_dir.glob("*.epub") if fnmatch.fnmatch(path.name, pattern)]
    if len(matches) != 1:
        raise ValueError(f"Pattern {pattern!r} matched {len(matches)} EPUBs")
    return matches[0]


def load_ncx(path: Path) -> tuple[str, ET.Element]:
    with zipfile.ZipFile(path) as epub:
        ncx_names = [name for name in epub.namelist() if name.lower().endswith(".ncx")]
        if len(ncx_names) != 1:
            raise ValueError(f"{path.name}: expected one NCX, found {len(ncx_names)}")
        return ncx_names[0], ET.fromstring(epub.read(ncx_names[0]))


def apply_replacements(path: Path, replacements: list[dict[str, str]]) -> tuple[str, bytes, list[dict[str, str]]]:
    ncx_name, root = load_ncx(path)
    evidence: list[dict[str, str]] = []

    for replacement in replacements:
        src = replacement["src"]
        old = replacement["old"]
        new = replacement["new"]
        matches: list[ET.Element] = []
        for point in root.findall(".//n:navPoint", NS):
            content = point.find("n:content", NS)
            label = point.find("n:navLabel/n:text", NS)
            if content is None or label is None:
                continue
            if content.attrib.get("src", "") == src and (label.text or "") == old:
                matches.append(label)
        if len(matches) != 1:
            raise ValueError(
                f"{path.name}: {old!r} at {src!r} matched {len(matches)} navPoints"
            )
        matches[0].text = new
        evidence.append({"src": src, "old": old, "new": new})

    return ncx_name, ET.tostring(root, encoding="utf-8", xml_declaration=True), evidence


def rewrite_epub(path: Path, ncx_name: str, ncx_data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(suffix=".epub", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temp_path, "w") as target:
            for info in source.infolist():
                data = ncx_data if info.filename == ncx_name else source.read(info.filename)
                target.writestr(info, data)
        with zipfile.ZipFile(temp_path) as check:
            if check.testzip() is not None:
                raise ValueError(f"{path.name}: rewritten EPUB failed ZIP validation")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.spec.read_text(encoding="utf-8"))
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.apply and args.backup_dir is None:
        parser.error("--backup-dir is required with --apply")
    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)

    for book in data["books"]:
        path = find_book(args.input_dir, book["file"])
        ncx_name, ncx_data, evidence = apply_replacements(path, book["replacements"])
        evidence_path = args.evidence_dir / f"{path.stem}.json"
        evidence_path.write_text(
            json.dumps({"file": path.name, "ncx": ncx_name, "replacements": evidence}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"VALID {path.name}: {len(evidence)} label replacements")
        if args.apply:
            backup_path = args.backup_dir / path.name
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
            rewrite_epub(path, ncx_name, ncx_data)
            print(f"APPLIED {path.name}")

    if not args.apply:
        print("Dry run only; no EPUB files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
