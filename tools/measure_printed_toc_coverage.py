#!/usr/bin/env python
"""Measure how faithfully the applied TOC restores the printed TOC.

Policy implemented here: the printed TOC is the specification for the entry
set (labels, hierarchy presence, order); the body is the specification for
targets; page numbers are discarded. Read-only diagnostic — EPUBs are never
modified.

Without --spec: report-only. Re-extracts printed-TOC lines from body files
(blocks ending in leader+page locators), normalizes both sides (page suffixes
and punctuation stripped), and reports how many printed lines appear among
the NCX labels and vice versa. Wrapped titles are handled by also trying
consecutive line pairs.

With --spec: gate mode. The adjudicated coordinate/search spec is expected to
carry the restoration contract: every printed line is either restored as a
label, or declared in the book-level ``dropped`` list with a reason; every
label that is not in the printed TOC carries an entry-level ``deviation``
reason. Anything else is a silent deviation:

- silent missing: printed line neither restored nor declared dropped -> exit 3
- unexplained addition: label absent from the printed TOC without a deviation
  mark -> exit 4 (only with --strict-additions)

A book whose printed TOC is not detectable is reported as unmeasurable and
never guessed; use judgment (or re-run after improving extraction) there.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from build_toc_review_packets import (
    PAGE_ONLY_RE,
    TOC_RE,
    clean_text,
    extract_blocks,
    spine,
)
from epub_navigation import ncx_name

NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}

# Stricter than build_toc_review_packets.PAGE_SUFFIX_RE: a printed-TOC line
# must show an explicit leader (dots, ellipsis, pipe, slash) before the page
# number. The bare "whitespace + trailing digits" alternative used for label
# cleaning would swallow any body paragraph ending in a number.
LEADER_PAGE_RE = re.compile(
    r"(?:\.{2,}|…{1,}|·{2,}|\|{1,2}|/{1,2})\s*[\[（(]?\d{1,4}[\]）)]?\s*$"
)
PIPE_END_RE = re.compile(r"\|\s*$")

# Same normalization family as extract_toc_evidence.normalize_key, plus the
# pipe separators some OCR renders in place of dot leaders.
KEY_STRIP_RE = re.compile(
    r"[\s\u3000,，.。:：;；/、·．…!！?？\-—–_()（）\[\]【】{}《》<>\"'“”‘’|｜/\\]+"
)

# A spine file counts as a printed-TOC page when this share of its blocks
# carry a page locator, with enough hits to rule out stray references.
MIN_LOCATOR_SHARE = 0.4
MIN_LOCATOR_HITS = 5


def key(value: str) -> str:
    return KEY_STRIP_RE.sub("", value).lower()


def strip_page_suffix(text: str) -> str:
    # Mirror the detection regexes: drop a bare trailing pipe first, then the
    # leader+page form (……12, |289) that LEADER_PAGE_RE anchors at the end.
    return LEADER_PAGE_RE.sub("", PIPE_END_RE.sub("", text)).strip(" .．。·…/")


def looks_like_toc_line(text: str) -> bool:
    return bool(LEADER_PAGE_RE.search(text) or PIPE_END_RE.search(text))


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
            stripped = strip_page_suffix(text)
            if len(stripped) < 2:
                continue
            if PAGE_ONLY_RE.match(stripped) or TOC_RE.match(stripped):
                continue
            lines.append(stripped)
    return lines


def spec_labels(book_spec: dict) -> tuple[set[str], set[str], set[str], set[str]]:
    """Flatten a spec book into (label keys, deviation-marked keys, dropped
    keys, renamed-from printed keys).

    ``printed`` on an entry declares which printed-TOC line it restores when
    the label had to differ (e.g. the printed line is OCR-damaged and the
    label was taken from the body heading)."""
    labels: set[str] = set()
    deviations: set[str] = set()
    renamed_from: set[str] = set()

    def walk(entries: list[dict]) -> None:
        for entry in entries:
            label_key = key(entry.get("label", ""))
            if label_key:
                labels.add(label_key)
                if entry.get("deviation"):
                    deviations.add(label_key)
            if entry.get("printed"):
                renamed_from.add(key(entry["printed"]))
            walk(entry.get("children") or [])

    walk(book_spec.get("entries") or [])
    dropped = {key(item.get("line", "")) for item in book_spec.get("dropped") or []}
    return labels, deviations, dropped, renamed_from


def account(
    lines: list[str],
    label_keys: set[str],
    deviation_keys: set[str] = frozenset(),
    dropped_keys: set[str] = frozenset(),
    renamed_keys: set[str] = frozenset(),
) -> dict[str, object]:
    """Classify printed lines and labels under the restoration contract."""
    restored = 0
    explained = 0
    silent_missing: list[str] = []
    index = 0
    while index < len(lines):
        line_key = key(lines[index])
        pair_key = key(lines[index] + lines[index + 1]) if index + 1 < len(lines) else ""
        if line_key in label_keys or pair_key in label_keys:
            restored += 1 if line_key in label_keys else 2
            index += 1 if line_key in label_keys else 2
            continue
        if line_key in renamed_keys or pair_key in renamed_keys:
            restored += 1 if line_key in renamed_keys else 2
            index += 1 if line_key in renamed_keys else 2
            continue
        if line_key in dropped_keys or pair_key in dropped_keys:
            explained += 1 if line_key in dropped_keys else 2
            index += 1 if line_key in dropped_keys else 2
            continue
        silent_missing.append(lines[index])
        index += 1

    printed_keys = {key(line) for line in lines}
    printed_keys |= {key(lines[i] + lines[i + 1]) for i in range(len(lines) - 1)}
    unexplained_additions = [
        label for label in label_keys
        if label not in printed_keys and label not in deviation_keys
    ]
    return {
        "restored": restored,
        "explained": explained,
        "silent_missing": silent_missing,
        "unexplained_additions": unexplained_additions,
    }


def measure_book(path: Path, book_spec: dict | None) -> dict[str, object]:
    with zipfile.ZipFile(path) as epub:
        lines = printed_toc_lines(epub)
        labels = (
            None if book_spec is None else spec_labels(book_spec)
        )
        ncx = ncx_labels(epub) if book_spec is None else None

    row: dict[str, object] = {
        "book": path.name,
        "has_printed_toc": bool(lines),
    }
    if book_spec is None:
        row.update(
            mode="report",
            printed_lines=len(lines),
            printed_matched=0,
            ncx_entries=len(ncx or []),
        )
        if lines:
            matched, unmatched = match_report(lines, {key(label) for label in ncx or []})
            row["printed_matched"] = matched
            row["printed_coverage"] = round(matched / len(lines), 4)
            row["unmatched_samples"] = [line[:40] for line in unmatched[:5]]
        else:
            row["printed_coverage"] = ""
        return row

    label_keys, deviation_keys, dropped_keys, renamed_keys = labels
    result = account(lines, label_keys, deviation_keys, dropped_keys, renamed_keys)
    row.update(
        mode="gate",
        printed_lines=len(lines),
        restored=result["restored"],
        explained_dropped=result["explained"],
        silent_missing=len(result["silent_missing"]),
        unexplained_additions=len(result["unexplained_additions"]),
        spec_entries=len(label_keys),
        deviation_marked=len(deviation_keys),
        declared_dropped=len(dropped_keys),
    )
    row["silent_missing_samples"] = [line[:40] for line in result["silent_missing"][:5]]
    return row


def match_report(lines: list[str], ncx_keys: set[str]) -> tuple[int, list[str]]:
    """Report-only matching used when no spec is supplied."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", help="Directory of EPUBs")
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Adjudicated spec (search or coordinate) with deviation/dropped marks; "
        "enables gate mode with nonzero exit on silent deviations",
    )
    parser.add_argument(
        "--strict-additions",
        action="store_true",
        help="With --spec: also fail on labels absent from the printed TOC "
        "without a deviation mark",
    )
    parser.add_argument("--csv-output", default="", help="Optional per-book CSV path")
    parser.add_argument("--worst", type=int, default=10, help="How many worst books to list")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    books = sorted(input_dir.glob("*.epub"))
    if not books:
        print(f"No EPUBs found in {input_dir}", file=sys.stderr)
        return 2

    specs: dict[str, dict] = {}
    if args.spec is not None:
        data = json.loads(args.spec.read_text(encoding="utf-8"))
        specs = {entry["file"]: entry for entry in data["books"]}

    rows: list[dict[str, object]] = []
    failures = 0
    for book in books:
        book_spec = None
        if args.spec is not None:
            matches = [name for name in specs if name == book.name or Path(name).stem in book.stem]
            if not matches:
                rows.append({"book": book.name, "error": "no spec entry"})
                continue
            book_spec = specs[matches[0]]
        try:
            rows.append(measure_book(book, book_spec))
        except Exception as error:  # unreadable books are reported, not fatal
            failures += 1
            rows.append({"book": book.name, "error": str(error)[:80]})
            continue

    if args.spec is None:
        report_mode_summary(rows, failures, args.worst)
    else:
        exit_code = gate_mode_summary(rows, failures, args.strict_additions)

    if args.csv_output:
        write_csv(rows, args.csv_output)
    return 0 if args.spec is None else exit_code


def report_mode_summary(rows: list[dict[str, object]], failures: int, worst: int) -> None:
    ok = [row for row in rows if "error" not in row]
    with_toc = [row for row in ok if row["has_printed_toc"]]
    without_toc = [row for row in ok if not row["has_printed_toc"]]

    total_printed = sum(int(row["printed_lines"]) for row in with_toc)
    total_matched = sum(int(row["printed_matched"]) for row in with_toc)

    print(f"books: {len(rows)} measured, {len(without_toc)} without printed TOC, {failures} unreadable")
    if total_printed:
        print(f"printed-TOC lines matched into NCX: {total_matched}/{total_printed}"
              f" = {total_matched / total_printed:.1%}")

    coverages = [float(row["printed_coverage"]) for row in with_toc if row["printed_coverage"] != ""]
    if coverages:
        print(f"per-book printed coverage: median {statistics.median(coverages):.1%},"
              f" min {min(coverages):.1%}, max {max(coverages):.1%}")
        worst_rows = sorted(
            with_toc, key=lambda row: float(row["printed_coverage"])
        )[:worst]
        print(f"\n{len(worst_rows)} lowest printed-TOC coverage:")
        for row in worst_rows:
            print(f"  {float(row['printed_coverage']):6.1%}  {row['book'][:60]}"
                  f"  ({row['printed_matched']}/{row['printed_lines']})")
            for sample in row["unmatched_samples"]:
                print(f"          unmatched: {sample}")


def gate_mode_summary(rows: list[dict[str, object]], failures: int, strict_additions: bool) -> int:
    gate_rows = [row for row in rows if row.get("mode") == "gate"]
    unmeasurable = [row for row in gate_rows if not row["has_printed_toc"]]
    measurable = [row for row in gate_rows if row["has_printed_toc"]]

    total_missing = sum(int(row["silent_missing"]) for row in measurable)
    total_additions = sum(int(row["unexplained_additions"]) for row in measurable)
    total_restored = sum(int(row["restored"]) for row in measurable)
    total_declared = sum(
        int(row["explained_dropped"]) + int(row["deviation_marked"]) for row in measurable
    )
    print(f"books in spec: {len(rows)}, measurable: {len(measurable)},"
          f" unmeasurable (no detectable printed TOC): {len(unmeasurable)},"
          f" errors: {failures}")
    print(f"restored: {total_restored} lines, declared deviations: {total_declared}")
    print(f"silent missing lines: {total_missing}")
    print(f"unexplained additions: {total_additions}")

    failing = [row for row in measurable if int(row["silent_missing"])]
    if failing:
        print(f"\n{len(failing)} books with silent missing printed-TOC lines:")
        for row in sorted(failing, key=lambda row: -int(row["silent_missing"])):
            print(f"  {int(row['silent_missing']):4d} missing  {row['book'][:64]}")
            for sample in row["silent_missing_samples"]:
                print(f"          e.g. {sample}")

    exit_code = 3 if total_missing else 0
    if strict_additions and total_additions:
        exit_code = 4
    if exit_code == 0:
        print("coverage gate: PASS")
    else:
        print(f"coverage gate: FAIL (exit {exit_code})", file=sys.stderr)
    return exit_code


def write_csv(rows: list[dict[str, object]], path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for name in row:
            if name not in fieldnames:
                fieldnames.append(name)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nper-book CSV: {output}")


if __name__ == "__main__":
    raise SystemExit(main())
