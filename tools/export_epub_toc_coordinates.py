#!/usr/bin/env python
"""Export the current EPUB NCX hierarchy as exact block-coordinate specs."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from build_toc_review_packets import clean_text, spine
from epub_navigation import ncx_name, content_nodes, resolve_href, target_block


NCX = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]


def export_book(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as epub:
        files = spine(epub)
        file_set = set(epub.namelist())
        navigation = ncx_name(epub)
        root = ET.fromstring(epub.read(navigation))
        nav_map = root.find("n:navMap", NCX)
        if nav_map is None:
            raise ValueError(f"{path.name}: NCX has no navMap")

        soup_cache: dict[str, BeautifulSoup] = {}
        nodes_cache: dict[str, list[Tag]] = {}

        def resolve(src: str, label: str) -> tuple[str, int, str]:
            file_name, fragment = resolve_href(src, navigation)
            if file_name not in file_set or file_name not in files:
                raise ValueError(f"{path.name}: navigation target file is not in the spine: {src}")
            if file_name not in soup_cache:
                soup_cache[file_name] = BeautifulSoup(epub.read(file_name), "lxml")
                nodes_cache[file_name] = content_nodes(soup_cache[file_name])
            soup = soup_cache[file_name]
            nodes = nodes_cache[file_name]

            block, target = target_block(soup, nodes, fragment)
            text = clean_text(target.get_text(" ", strip=True))
            return file_name, block, text[:80]

        def walk(parent: ET.Element) -> list[dict[str, Any]]:
            result = []
            for point in parent.findall("n:navPoint", NCX):
                label_node = point.find("n:navLabel/n:text", NCX)
                content = point.find("n:content", NCX)
                label = clean_text(label_node.text or "") if label_node is not None else ""
                src = content.attrib.get("src", "") if content is not None else ""
                if not label or not src:
                    raise ValueError(f"{path.name}: empty NCX label or target")
                file_name, block, expect = resolve(src, label)
                entry: dict[str, Any] = {
                    "label": label,
                    "file": file_name,
                    "block": block,
                    "expect": expect,
                }
                children = walk(point)
                if children:
                    entry["children"] = children
                result.append(entry)
            return result

        return {"file": path.name, "entries": walk(nav_map)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    paths = sorted(args.epub_dir.glob("*.epub"))
    if not paths:
        raise ValueError(f"No EPUB files found in {args.epub_dir}")
    books = [export_book(path) for path in paths]
    payload = {
        "version": 1,
        "description": "Accepted EPUB TOC hierarchy and exact body block coordinates.",
        "books": books,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(books)} EPUB TOCs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
