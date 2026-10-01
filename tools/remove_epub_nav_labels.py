#!/usr/bin/env python
"""Remove selected NCX navPoint labels from an EPUB."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
ET.register_namespace("", NCX_NS)


def nav_label(nav_point: ET.Element) -> str:
    label = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
    return (label.text or "").strip() if label is not None else ""


def nav_src(nav_point: ET.Element) -> str:
    content = nav_point.find(f"{{{NCX_NS}}}content")
    return (content.attrib.get("src", "") if content is not None else "").strip()


def remove_matching(parent: ET.Element, labels: set[str], srcs: set[str]) -> int:
    removed = 0
    for child in list(parent):
        if child.tag != f"{{{NCX_NS}}}navPoint":
            continue
        removed += remove_matching(child, labels, srcs)
        if nav_label(child) in labels or nav_src(child) in srcs:
            parent.remove(child)
            removed += 1
    return removed


def renumber(root: ET.Element) -> None:
    for index, nav_point in enumerate(root.iter(f"{{{NCX_NS}}}navPoint"), start=1):
        nav_point.set("playOrder", str(index))


def write_entry(dst: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> None:
    new_info = zipfile.ZipInfo(info.filename, info.date_time)
    new_info.comment = info.comment
    new_info.extra = info.extra
    new_info.internal_attr = info.internal_attr
    new_info.external_attr = info.external_attr
    new_info.create_system = info.create_system
    new_info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
    dst.writestr(new_info, data)


def remove_labels(epub_path: Path, labels: set[str], srcs: set[str], apply: bool) -> int:
    with zipfile.ZipFile(epub_path, "r") as src:
        infos = src.infolist()
        ncx_info = next((info for info in infos if info.filename.lower().endswith(".ncx")), None)
        if ncx_info is None:
            return 0
        root = ET.fromstring(src.read(ncx_info.filename))
        nav_map = root.find(f"{{{NCX_NS}}}navMap")
        if nav_map is None:
            return 0
        removed = remove_matching(nav_map, labels, srcs)
        renumber(root)
        if not apply or not removed:
            return removed
        ncx_data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        fd, temp_name = tempfile.mkstemp(prefix=epub_path.stem + ".", suffix=".epub", dir=str(epub_path.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with zipfile.ZipFile(temp_path, "w") as dst:
                mimetype = next((info for info in infos if info.filename == "mimetype"), None)
                ordered = ([mimetype] if mimetype else []) + [info for info in infos if info is not mimetype]
                for info in ordered:
                    data = ncx_data if info.filename == ncx_info.filename else src.read(info.filename)
                    write_entry(dst, info, data)
            shutil.move(str(temp_path), str(epub_path))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub", type=Path)
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--src", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    removed = remove_labels(args.epub, set(args.label), set(args.src), args.apply)
    action = "removed" if args.apply else "would remove"
    print(f"{args.epub.name}: {action} {removed} nav entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
