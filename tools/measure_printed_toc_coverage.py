#!/usr/bin/env python
"""Measure how faithfully final NCX labels restore the printed TOC.

Diagnostic only: reads EPUBs, never modifies them. For each book it
re-extracts the printed-TOC lines from body files (blocks ending in page
locators), normalizes both sides (page suffixes and punctuation stripped),
and reports how many printed lines appear among NCX labels and vice versa.
Wrapped titles are handled by also trying consecutive line pairs.

A low printed-TOC coverage means the applied navigation dropped or renamed
entries relative to the book's own contents page. A low NCX coverage means
the navigation contains entries the printed TOC never listed. Neither is
automatically wrong (OCR damage on the printed page, body headings used as
the more accurate label source), but the numbers make the deviation visible
instead of silent.
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from build_toc_review_packets import (
    PAGE_ONLY_RE,
    PAGE_SUFFIX_RE,
    TOC_RE,
    clean_text,
    extract_blocks,
    spine,
)
from epub_navigation import ncx_name

NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}

# Same normalization family as extract_toc_evidence.normalize_key, plus the
# pipe separators some OCR renders in place of dot leaders.
KEY_STRIP_RE = re.compile(
    r"[\s\u3000,，.。:：;；/、·．…!！?？\-—–_()（）\[\]【】{}《》<>\"'“”‘’|｜/\\]+"
)

# Stricter than build_toc_review_packets.PAGE_SUFFIX_RE: a printed-TOC line
# must show an explicit leader (dots, ellipsis, pipe, slash) before the page
# number. The bare "whitespace + trailing digits" alternative used for label
# cleaning would swallow any body paragraph ending in a number.
LEADER_PAGE_RE = re.compile(
    r"(?:\.{2,}|…{1,}|·{2,}|\|{1,2}|/{1,2})\s*[\[（(]?\d{1,4}[\]）)]?\s*$"
)
PIPE_END_RE = re.compile(r"\|\s*$")

# A spine file counts as a printed-TOC page when this share of its blocks
# carry a page locator, with enough hits to rule out stray references.
MIN_LOCATOR_SHARE = 0.4
MIN_LOCATOR_HITS = 5


def looks_like_toc_line(text: str) -> bool:
    return bool(LEADER_PAGE_RE.search(text) or PIPE_END_RE.search(text))


def key(value: str) -> str:
    return KEY_STRIP_RE.sub("", value).lower()


def strip_page_suffix(text: str) -> str:
    return PAGE_SUFFIX_RE.sub("", text).strip(" .．。·…/")


def ncx_labels(epub: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(epub.read(ncx_name(epub)))
    labels: list[str] = []
    for node in root.findall(".//n:navMap//n:navPoint/n:navLabel/n:text", NCX_NS):
        label = clean_text(node.text or "")
        if label:
            labels.append(label)
    return labels


def printed_toc_lines(epub: zipfile.ZipFile) -> list[str]:
    files = spine(epub)
    blocks = extract_blocks(epub, files)
    by_file: dict[str, list[str]] = {}
    for block in blocks:
        by_file.setdefault(block.file_name, []).append(block.text)
    lines: list[str] = []
    for file_name in files:
        texts = by_file.get(file_name, [])
        hits = [text for text in texts if looks_like_toc_line(text)]
        if len(hits) < MIN_LOCATOR_HITS or len(hits) < MIN_LOCATOR_SHARE * len(texts):
            continue
        for text in hits:
            stripped = strip_page_suffix(text).rstrip("|").strip(" .．。·…/")
            if len(stripped) < 2:
                continue
            if PAGE_ONLY_RE.match(stripped) or TOC_RE.match(stripped):
                continue
            lines.append(stripped)
    return lines


def match_lines(lines: list[str], ncx_keys: set[str]) -> tuple[int, list[str]]:
    matched = 0
    unmatched: list[str] = []
    index = 0
    while index < len(lines):
        if key(lines[index]) in ncx_keys:
            matched += 1
            index += 1
            continue
        if (
            index + 1 < len(lines)
            and key(lines[index] + lines[index + 1]) in ncx_keys
        ):
            matched += 2
            index += 2
            continue
        unmatched.append(lines[index])
        index += 1
    return matched, unmatched


def measure_book(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as epub:
        labels = ncx_labels(epub)
        lines = printed_toc_lines(epub)
    ncx_keys = {key(label) for label in labels}
    line_keys = {key(line) for line in lines}
    matched_lines, unmatched = match_lines(lines, ncx_keys)
    matched_labels = sum(1 for label in labels if key(label) in line_keys)
    return {
        "book": path.name,
        "has_printed_toc": bool(lines),
        "printed_lines": len(lines),
        "printed_matched": matched_lines,
        "printed_coverage": round(matched_lines / len(lines), 4) if lines else "",
        "ncx_entries": len(labels),
        "ncx_matched": matched_labels,
        "ncx_coverage": round(matched_labels / len(labels), 4) if labels else "",
        "unmatched_samples": [line[:40] for line in unmatched[:5]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", help="Directory of accepted EPUBs")
    parser.add_argument("--csv-output", default="", help="Optional per-book CSV path")
    parser.add_argument("--worst", type=int, default=10, help="How many worst books to list")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    books = sorted(input_dir.glob("*.epub"))
    if not books:
        print(f"No EPUBs found in {input_dir}", file=sys.stderr)
        return 2

    rows: list[dict[str, object]] = []
    failures = 0
    for book in books:
        try:
            rows.append(measure_book(book))
        except Exception as error:  # unreadable books are reported, not fatal
            failures += 1
            rows.append({"book": book.name, "error": str(error)[:80]})
            continue

    ok = [row for row in rows if "error" not in row]
    with_toc = [row for row in ok if row["has_printed_toc"]]
    without_toc = [row for row in ok if not row["has_printed_toc"]]

    total_printed = sum(int(row["printed_lines"]) for row in with_toc)
    total_printed_matched = sum(int(row["printed_matched"]) for row in with_toc)
    total_ncx = sum(int(row["ncx_entries"]) for row in with_toc)
    total_ncx_matched = sum(int(row["ncx_matched"]) for row in with_toc)

    print(f"books: {len(books)} measured, {len(without_toc)} without printed TOC, {failures} unreadable")
    if total_printed:
        print(f"printed-TOC lines matched into NCX: {total_printed_matched}/{total_printed}"
              f" = {total_printed_matched / total_printed:.1%}")
    if total_ncx:
        print(f"NCX labels found in printed TOC:   {total_ncx_matched}/{total_ncx}"
              f" = {total_ncx_matched / total_ncx:.1%}")

    coverages = [float(row["printed_coverage"]) for row in with_toc]
    if coverages:
        print(f"per-book printed coverage: median {statistics.median(coverages):.1%},"
              f" min {min(coverages):.1%}, max {max(coverages):.1%}")

    worst = sorted(with_toc, key=lambda row: float(row["printed_coverage"]))[: args.worst]
    if worst:
        print(f"\n{len(worst)} lowest printed-TOC coverage:")
        for row in worst:
            print(f"  {float(row['printed_coverage']):6.1%}  {row['book'][:60]}"
                  f"  ({row['printed_matched']}/{row['printed_lines']})")
            for sample in row["unmatched_samples"]:
                print(f"          unmatched: {sample}")

    if args.csv_output:
        output = Path(args.csv_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nper-book CSV: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
