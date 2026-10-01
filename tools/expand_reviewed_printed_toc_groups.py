#!/usr/bin/env python
"""Expand manually bounded printed-TOC groups into a reviewed search spec."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from build_toc_review_packets import clean_text, extract_blocks, nav_items, spine


PAGE_SUFFIX_RE = re.compile(r"(?:\s*(?:[._·•…⋯]{1,}|[/／]{1,2})\s*|\s+)\d{1,4}\s*$")
ATTACHED_PAGE_SUFFIX_RE = re.compile(r"(?<=[：:，,。.!！?？）》）\]])\s*\d{1,4}\s*$")
PAREN_PAGE_SUFFIX_RE = re.compile(r"\s*[（(]\s*\d{1,4}\s*[）)]\s*$")


def clean_label(text: str) -> str:
    previous = text.strip()
    while True:
        current = PAREN_PAGE_SUFFIX_RE.sub(
            "", ATTACHED_PAGE_SUFFIX_RE.sub("", PAGE_SUFFIX_RE.sub("", previous))
        ).strip().rstrip("./／").strip()
        if current == previous:
            return current
        previous = current


def find_book(directory: Path, pattern: str) -> Path:
    exact = directory / pattern
    if exact.is_file():
        return exact
    matches = [path for path in directory.glob("*.epub") if fnmatch.fnmatch(path.name, pattern)]
    if len(matches) != 1:
        raise ValueError(f"Expected one match for {pattern!r}, found {len(matches)}")
    return matches[0]


def coordinate(entry: dict[str, Any]) -> tuple[int, int]:
    return int(entry["file_index"]), int(entry["block"])


def nav_coordinates(epub: zipfile.ZipFile, files: list[str], blocks: list[Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in nav_items(epub, files, blocks):
        label_key = re.sub(r"\s+", "", str(item["label"]))
        src_file, _, fragment = urllib.parse.unquote(str(item["src"])).partition("#")
        if src_file not in epub.namelist():
            raise ValueError(f"Missing current navigation file {src_file}")
        soup = BeautifulSoup(epub.read(src_file), "lxml")
        nodes = [
            node for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"])
            if clean_text(node.get_text(" ", strip=True))
        ]
        if fragment:
            anchor = soup.find(id=fragment)
            if anchor is None:
                raise ValueError(f"Missing current navigation anchor {src_file}#{fragment}")
            parent = anchor.find_parent(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"])
            target = parent if parent in nodes else anchor.find_next(
                ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]
            )
        else:
            target = nodes[0] if nodes else None
        if target is None or target not in nodes:
            raise ValueError(f"No content block after current navigation target {src_file}#{fragment}")
        result.setdefault(label_key, []).append({
            "file": src_file,
            "block": nodes.index(target),
            "expect": clean_text(target.get_text(" ", strip=True))[:80],
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("adjudication", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = json.loads(args.adjudication.read_text(encoding="utf-8"))
    output_books = []
    for book in data["books"]:
        path = find_book(args.input_dir, book["file"])
        with zipfile.ZipFile(path) as epub:
            files = spine(epub)
            blocks = extract_blocks(epub, files)
            current_targets = nav_coordinates(epub, files, blocks)
        by_coordinate = {(block.file_index, block.block_index): block for block in blocks}
        by_source = {(block.file_name, block.block_index): block for block in blocks}

        def expand_item(item: dict[str, Any]) -> dict[str, Any]:
            if book.get("use_current_nav_targets") and "file" not in item:
                label_key = re.sub(r"\s+", "", item.get("current_label", item["label"]))
                candidates = current_targets.get(label_key, [])
                occurrence = int(item.get("current_occurrence", 1))
                if not candidates or occurrence < 1 or occurrence > len(candidates):
                    raise ValueError(f"No unique current navigation target for {item['label']!r}")
                if len(candidates) > 1 and "current_occurrence" not in item:
                    raise ValueError(
                        f"Multiple current navigation targets for {item['label']!r}; "
                        "set current_occurrence"
                    )
                target = dict(candidates[occurrence - 1])
                rewind = int(item.get("rewind", book.get("nav_target_rewind", 0)))
                if rewind:
                    target["block"] -= rewind
                    source_block = by_source.get((target["file"], target["block"]))
                    if source_block is None:
                        raise ValueError(f"Cannot rewind current target for {item['label']!r}")
                    target["expect"] = source_block.text[:80]
                result = {"label": item["label"], **target}
            else:
                result = {
                    "label": item["label"],
                    "file": item["file"],
                    "block": int(item["block"]),
                    "expect": item["expect"],
                }
            printed = item.get("printed")
            children = []
            if printed:
                start = coordinate(printed["start"])
                end = coordinate(printed["end"])
                selected = [
                    block for block in blocks
                    if start <= (block.file_index, block.block_index) <= end
                ]
                search_overrides = printed.get("search_overrides", {})
                for block in selected:
                    texts = [block.text]
                    if printed.get("split_pattern"):
                        texts = re.split(str(printed["split_pattern"]), block.text)
                    for text in texts:
                        label = clean_label(text)
                        if not label or label in set(printed.get("exclude", [])):
                            continue
                        search = search_overrides.get(label, label)
                        if isinstance(search, str):
                            children.append({"label": label, "search": search, "exact": True})
                        else:
                            children.append({"label": label, **search})
            for child in item.get("children", []):
                if isinstance(child, str):
                    children.append({"label": child, "search": child, "exact": True})
                else:
                    children.append(dict(child))
            children.extend(expand_item(child) for child in item.get("entries", []))
            if printed and not children:
                raise ValueError(f"No printed children for {item['label']} in {path.name}")
            if children:
                result["children"] = children
            return result

        entries = [expand_item(item) for item in book["entries"]]
        output_books.append({"file": book["file"], "entries": entries})
        print(f"EXPANDED {path.name}: {len(entries)} top-level entries")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"books": output_books}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
