#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import html.parser
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


class HtmlStats(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.images: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self._heading_level: int | None = None
        self._heading_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        tag = tag.lower()
        if tag == "img":
            self.images.append(attrs_dict.get("src", ""))
        if re.fullmatch(r"h[1-6]", tag):
            self._heading_level = int(tag[1])
            self._heading_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._heading_level is not None and tag == f"h{self._heading_level}":
            text = normalize_text("".join(self._heading_text))
            if text:
                self.headings.append((self._heading_level, text))
            self._heading_level = None
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        if data:
            self.text_parts.append(data)
            if self._heading_level is not None:
                self._heading_text.append(data)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_zip_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8", errors="replace")


def count_nav_items(zf: zipfile.ZipFile, names: list[str]) -> int:
    total = 0
    for name in names:
        lower = name.lower()
        if lower.endswith(".ncx"):
            try:
                root = ET.fromstring(zf.read(name))
                total += len(root.findall(".//{*}navPoint"))
            except ET.ParseError:
                pass
        elif lower.endswith((".xhtml", ".html", ".htm")) and "nav" in lower:
            text = read_zip_text(zf, name)
            total += len(re.findall(r"<a\b", text, flags=re.I))
    return total


def audit_epub(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        html_names = [
            n for n in names
            if n.lower().endswith((".xhtml", ".html", ".htm")) and not n.lower().endswith("nav.xhtml")
        ]
        image_files = [
            n for n in names
            if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"))
        ]
        parser = HtmlStats()
        parse_errors = 0
        for name in html_names:
            try:
                parser.feed(read_zip_text(zf, name))
            except Exception:
                parse_errors += 1
        existing = set(names)
        broken_images = 0
        for html_name in html_names:
            base = Path(html_name).parent
            try:
                stats = HtmlStats()
                stats.feed(read_zip_text(zf, html_name))
            except Exception:
                continue
            for src in stats.images:
                clean = src.split("#", 1)[0].split("?", 1)[0]
                if not clean:
                    broken_images += 1
                    continue
                resolved = (base / clean).as_posix()
                if clean not in existing and resolved not in existing:
                    broken_images += 1

        text = normalize_text(" ".join(parser.text_parts))
        nav_items = count_nav_items(zf, names)
        heading_texts = [h[1] for h in parser.headings]
        unique_headings = len(set(heading_texts))
        duplicate_heading_count = max(0, len(heading_texts) - unique_headings)

        return {
            "name": path.name,
            "bytes": path.stat().st_size,
            "html_files": len(html_names),
            "image_files": len(image_files),
            "image_refs": len(parser.images),
            "broken_image_refs": broken_images,
            "text_chars": len(text),
            "headings": len(parser.headings),
            "unique_headings": unique_headings,
            "duplicate_headings": duplicate_heading_count,
            "nav_items": nav_items,
            "parse_errors": parse_errors,
        }


def iter_blocks(data):
    if isinstance(data, dict):
        if "type" in data:
            yield data
        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from iter_blocks(value)
    elif isinstance(data, list):
        for item in data:
            yield from iter_blocks(item)


def audit_mineru_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    counts: dict[str, int] = {}
    visual_with_path = 0
    for block in iter_blocks(data):
        block_type = str(block.get("type", ""))
        counts[block_type] = counts.get(block_type, 0) + 1
        content = block.get("content")
        image_source = content.get("image_source") if isinstance(content, dict) else None
        if isinstance(image_source, dict) and image_source.get("path"):
            visual_with_path += 1
        elif block.get("img_path") or block.get("image_path"):
            visual_with_path += 1
    return {
        "json": str(path),
        "blocks": sum(counts.values()),
        "visual_with_path": visual_with_path,
        "types": json.dumps(counts, ensure_ascii=False, sort_keys=True),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epub-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--mineru-output", type=Path)
    args = parser.parse_args()

    rows = [audit_epub(path) for path in sorted(args.epub_dir.glob("*.epub"))]
    fields = [
        "name", "bytes", "html_files", "image_files", "image_refs", "broken_image_refs",
        "text_chars", "headings", "unique_headings", "duplicate_headings", "nav_items", "parse_errors",
    ]
    if args.csv_output:
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(f"EPUB files: {len(rows)}")
    print(f"Total image files: {sum(int(r['image_files']) for r in rows)}")
    print(f"Total image refs: {sum(int(r['image_refs']) for r in rows)}")
    print(f"Broken image refs: {sum(int(r['broken_image_refs']) for r in rows)}")
    print("Lowest image count:")
    for row in sorted(rows, key=lambda r: (int(r["image_files"]), int(r["bytes"])))[:12]:
        print(f"  {row['image_files']:>4} images | {row['nav_items']:>4} toc | {row['text_chars']:>7} chars | {row['name']}")
    print("Largest TOCs:")
    for row in sorted(rows, key=lambda r: int(r["nav_items"]), reverse=True)[:12]:
        print(f"  {row['nav_items']:>4} toc | {row['headings']:>4} headings | {row['name']}")

    if args.work_dir:
        json_rows = [audit_mineru_json(path) for path in sorted(args.work_dir.glob("*/mineru/**/*_content_list_v2.json"))]
        if args.mineru_output:
            args.mineru_output.parent.mkdir(parents=True, exist_ok=True)
            with args.mineru_output.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["json", "blocks", "visual_with_path", "types"])
                writer.writeheader()
                writer.writerows(json_rows)
        print(f"MinerU JSON files: {len(json_rows)}")
        for row in json_rows:
            print(f"  {row['visual_with_path']:>4} visual paths | {row['blocks']:>6} blocks | {row['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
