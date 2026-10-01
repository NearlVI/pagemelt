#!/usr/bin/env python
"""Build the manually reviewed TOC coordinates for the CBT 123-techniques EPUB."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from build_toc_review_packets import extract_blocks, spine


BOOK_NAME = "认知行为疗法123项实用技术-306黑白.epub"
CHAPTER_LABELS = {
    "第1章": "第1章 识别与评估",
    "第7章": "第7章 成长经验修复",
}


def coordinate(label: str, block) -> dict[str, object]:
    return {
        "label": label,
        "file": block.file_name,
        "block": block.block_index,
        "expect": block.text,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    epub_path = args.epub_dir / BOOK_NAME
    with zipfile.ZipFile(epub_path) as epub:
        files = spine(epub)
        blocks = extract_blocks(epub, files)

    by_position = {(block.file_name, block.block_index): block for block in blocks}
    intro = by_position[("ebook_source_split_000.html", 242)]
    references = by_position[("ebook_source_split_007.html", 150)]
    if not intro.text.startswith("认知行为疗法（CBT）作为心理咨询或治疗的主流学派"):
        raise ValueError("Unexpected reviewed 导读 start")
    if not references.text.startswith("[1]"):
        raise ValueError("Unexpected reviewed 参考文献 start")

    entries: list[dict[str, object]] = [coordinate("导读", intro)]
    chapter = None
    section = None
    chapter_count = section_count = technique_heading_count = 0

    for block in blocks:
        if block.file_index < 2:
            continue
        if block.tag == "h1" and block.text.startswith("第") and "章" in block.text:
            label = CHAPTER_LABELS.get(block.text, block.text)
            chapter = coordinate(label, block)
            chapter["children"] = []
            entries.append(chapter)
            section = None
            chapter_count += 1
        elif block.tag == "h3" and chapter is not None:
            section = coordinate(block.text, block)
            section["children"] = []
            chapter["children"].append(section)
            section_count += 1
        elif block.tag == "h4" and section is not None:
            section["children"].append(coordinate(block.text, block))
            technique_heading_count += 1

    # Section 1.5 is itself the 123rd technique; unlike the other 122, it has no h4 child.
    leaf_sections = sum(
        1
        for item in entries
        for child in item.get("children", [])
        if not child.get("children")
    )
    if (chapter_count, section_count, technique_heading_count, leaf_sections) != (7, 24, 122, 1):
        raise ValueError(
            "Unexpected body hierarchy: "
            f"chapters={chapter_count}, sections={section_count}, "
            f"techniques={technique_heading_count}, leaf_sections={leaf_sections}"
        )

    def remove_empty_children(items: list[dict[str, object]]) -> None:
        for item in items:
            children = item.get("children")
            if not children:
                item.pop("children", None)
            else:
                remove_empty_children(children)

    entries.append(coordinate("参考文献", references))
    remove_empty_children(entries)

    result = {"books": [{"file": BOOK_NAME, "entries": entries}]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output}: {chapter_count} chapters, {section_count} sections, "
        f"{technique_heading_count + leaf_sections} techniques"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
