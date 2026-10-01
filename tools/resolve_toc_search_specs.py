#!/usr/bin/env python
"""Resolve reviewed TOC search descriptions to exact EPUB block coordinates."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from build_toc_review_packets import extract_blocks, spine


PUNCT_RE = re.compile(
    r"[\s\u3000,，。．、；：:！？?!·•●◆◇■□▪▫\-—–_()（）\[\]【】{}《》<>\"'“”‘’/\\]+"
)


def key(value: str) -> str:
    return PUNCT_RE.sub("", value).lower()


def find_book(input_dir: Path, pattern: str) -> Path:
    exact = input_dir / pattern
    if exact.is_file():
        return exact
    matches = [p for p in input_dir.glob("*.epub") if fnmatch.fnmatch(p.name, pattern)]
    if len(matches) != 1:
        raise ValueError(f"Pattern {pattern!r} matched {len(matches)} books")
    return matches[0]


def resolve_book(epub_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    with zipfile.ZipFile(epub_path) as epub:
        files = spine(epub)
        all_blocks = extract_blocks(epub, files)

    by_file: dict[str, list[Any]] = {}
    for block in all_blocks:
        by_file.setdefault(block.file_name, []).append(block)
    file_index = {name: i for i, name in enumerate(files)}
    cursor = [int(spec.get("start_file", 0)), int(spec.get("start_block", 0))]

    def resolve_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resolved_entries: list[dict[str, Any]] = []
        for entry in entries:
            if "file" in entry and "block" in entry:
                result = {
                    "label": entry["label"],
                    "file": entry["file"],
                    "block": int(entry["block"]),
                    "expect": entry.get("expect", ""),
                }
                cursor[:] = [file_index[result["file"]], result["block"] + 1]
            else:
                searches = entry.get("search") or entry["label"]
                if isinstance(searches, str):
                    searches = [searches]
                search_keys = [key(value) for value in searches if key(value)]
                if not search_keys:
                    raise ValueError(f"Empty search for {entry['label']}")

                start_file = max(cursor[0], int(entry.get("start_file", spec.get("start_file", 0))))
                start_block = cursor[1] if start_file == cursor[0] else 0
                max_file = int(entry.get("max_file", len(files) - 1))
                window_size = int(entry.get("window", 1))
                occurrence = int(entry.get("occurrence", 1))
                exact = bool(entry.get("exact", spec.get("exact", False)))
                found = None
                hit_count = 0
                for file_number in range(start_file, min(max_file, len(files) - 1) + 1):
                    doc_blocks = by_file.get(files[file_number], [])
                    begin = start_block if file_number == start_file else 0
                    for block_number in range(begin, len(doc_blocks)):
                        window = key(
                            " ".join(
                                block.text
                                for block in doc_blocks[block_number : block_number + window_size]
                            )
                        )
                        matched = (
                            window in search_keys
                            if exact
                            else all(search_key in window for search_key in search_keys)
                        )
                        if matched:
                            hit_count += 1
                            if hit_count == occurrence:
                                found = (file_number, block_number, doc_blocks[block_number])
                                break
                    if found:
                        break
                if not found:
                    raise ValueError(
                        f"{epub_path.name}: could not resolve {entry['label']!r} "
                        f"after {tuple(cursor)}; search={searches!r}"
                    )
                file_number, block_number, block = found
                result = {
                    "label": entry["label"],
                    "file": files[file_number],
                    "block": block_number,
                    "expect": block.text[:80],
                }
                cursor[:] = [file_number, block_number + 1]

            children = resolve_entries(entry.get("children") or [])
            if children:
                result["children"] = children
            resolved_entries.append(result)
        return resolved_entries

    return {"file": spec["file"], "entries": resolve_entries(spec["entries"])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("search_spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = json.loads(args.search_spec.read_text(encoding="utf-8"))
    resolved = []
    for spec in data["books"]:
        epub_path = find_book(args.input_dir, spec["file"])
        result = resolve_book(epub_path, spec)
        resolved.append(result)
        print(f"RESOLVED {epub_path.name}: {len(result['entries'])} top-level entries")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"books": resolved}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
