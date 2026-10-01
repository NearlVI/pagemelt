#!/usr/bin/env python
"""Transcribe the reviewed 1-100 printed contents into a search spec."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

from build_toc_review_packets import extract_blocks, spine


BOOK_PATTERN = "以人为中心疗法100个关键点与技巧*.epub"
TOC_FILE = "ebook_source_split_002.html"
PARTS = [
    (1, 7, "第一部分 以人为中心疗法的基本认识论、哲学观及原理", TOC_FILE, 143),
    (8, 22, "第二部分 经典以人为中心理论", "ebook_source_split_003.html", 5),
    (23, 38, "第三部分 回顾与反思：以人为中心理论的优势", "ebook_source_split_004.html", 4),
    (39, 50, "第四部分 以人为中心疗法的批判与反驳", "ebook_source_split_005.html", 5),
    (51, 84, "第五部分 以人为中心实践", "ebook_source_split_005.html", 114),
    (85, 88, "第六部分 有关生活事件反应的以人为中心理论与实践", "ebook_source_split_005.html", 408),
    (89, 100, "第七部分 新发展、优势和理解：为21世纪扩展以人为中心理论", "ebook_source_split_005.html", 449),
]


def printed_titles(epub_path: Path) -> dict[int, str]:
    with zipfile.ZipFile(epub_path) as epub:
        blocks = extract_blocks(epub, spine(epub))
    lines = [
        block.text
        for block in blocks
        if block.file_name == TOC_FILE and 8 <= block.block_index <= 138
    ]

    titles: dict[int, str] = {}
    current_number: int | None = None
    fragments: list[str] = []

    def finish() -> None:
        nonlocal current_number, fragments
        if current_number is None:
            return
        value = " ".join(fragments)
        value = re.sub(r"\s*\d{3}\s*$", "", value).strip()
        titles[current_number] = value
        current_number = None
        fragments = []

    for line in lines:
        if line == "Part" or re.fullmatch(r"第[一二三四五六七]部分", line):
            finish()
            continue
        if re.fullmatch(r"\d{3}-?", line):
            continue
        match = re.match(r"^(\d{1,3})\s+(.+)$", line)
        expected_number = (current_number + 1) if current_number is not None else (len(titles) + 1)
        if match and int(match.group(1)) == expected_number:
            finish()
            current_number = int(match.group(1))
            fragments = [match.group(2)]
        elif current_number is not None:
            fragments.append(line)
    finish()

    expected = set(range(1, 101))
    if set(titles) != expected:
        missing = sorted(expected - set(titles))
        extra = sorted(set(titles) - expected)
        raise ValueError(f"Could not transcribe 1-100: missing={missing}, extra={extra}")
    # The printed contents repeats this typo; the body and intended titles do not.
    titles = {
        number: title.replace("以人为本中心", "以人为中心")
        for number, title in titles.items()
    }
    return titles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    matches = list(args.epub_dir.glob(BOOK_PATTERN))
    if len(matches) != 1:
        raise ValueError(f"Expected one EPUB, found {len(matches)}")
    titles = printed_titles(matches[0])

    entries = [
        {"label": "序", "file": "ebook_source_split_001.html", "block": 0, "expect": "序"}
    ]
    for first, last, label, file_name, block_index in PARTS:
        entries.append(
            {
                "label": label,
                "file": file_name,
                "block": block_index,
                "expect": label.split(" ", 1)[0],
                "children": [
                    {"label": f"{number} {titles[number]}", "search": titles[number]}
                    for number in range(first, last + 1)
                ],
            }
        )
    entries.extend(
        [
            {"label": "参考文献", "file": "ebook_source_split_006.html", "block": 0, "expect": "参考文献"},
        ]
    )
    data = {
        "books": [
            {
                "file": BOOK_PATTERN,
                "exact": True,
                "entries": entries,
            }
        ]
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Transcribed {len(titles)} reviewed key points to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
