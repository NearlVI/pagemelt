#!/usr/bin/env python
"""Build compact, evidence-rich EPUB packets for manual/LLM TOC review.

This intentionally does not decide what the TOC should be. It preserves enough
source order and context for a reviewer to distinguish a printed contents page
from real chapter starts.
"""

from __future__ import annotations

import argparse
import csv
import html
import posixpath
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}

SPACE_RE = re.compile(r"\s+")
CHAPTER_RE = re.compile(
    r"(?:"
    r"第\s*[一二三四五六七八九十百千万零〇两\d]+\s*[篇部卷编章节讲回]|"
    r"[上中下]\s*[篇部卷编]|"
    r"(?:chapter|part|section)\s+[0-9ivxlcdm]+\b|"
    r"^[0-9]{1,3}\s*[.、．]\s*[^0-9]"
    r")",
    re.IGNORECASE,
)
TOC_RE = re.compile(r"(?:^|\s)(?:目录|目次|contents?)(?:\s|$)", re.IGNORECASE)
PAGE_ONLY_RE = re.compile(r"^[\[（(]?\s*[ivxlcdm\d一二三四五六七八九十百]+\s*[\]）)]?$", re.IGNORECASE)
PAGE_SUFFIX_RE = re.compile(r"(?:\.{2,}|…{1,}|·{2,}|/{1,2}|\s)\s*[\[（(]?\d{1,4}[\]）)]?\s*$")


@dataclass
class Block:
    file_index: int
    file_name: str
    block_index: int
    tag: str
    text: str


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(value)).strip()


def decode_href(href: str, base: str = "") -> str:
    href = urllib.parse.unquote(href)
    if base:
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    return href


def get_opf_path(epub: zipfile.ZipFile) -> str:
    try:
        root = ET.fromstring(epub.read("META-INF/container.xml"))
        node = root.find(".//c:rootfile", CONTAINER_NS)
        if node is not None:
            return node.attrib["full-path"]
    except Exception:
        pass
    for name in epub.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ValueError("No OPF file found")


def spine(epub: zipfile.ZipFile) -> list[str]:
    opf_path = get_opf_path(epub)
    root = ET.fromstring(epub.read(opf_path))
    manifest: dict[str, str] = {}
    for item in root.findall(".//opf:manifest/opf:item", OPF_NS):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = decode_href(href, opf_path)
    result = []
    for itemref in root.findall(".//opf:spine/opf:itemref", OPF_NS):
        name = manifest.get(itemref.attrib.get("idref", ""), "")
        if Path(name).suffix.lower() in HTML_EXTENSIONS:
            result.append(name)
    return result or [n for n in epub.namelist() if Path(n).suffix.lower() in HTML_EXTENSIONS]


def extract_blocks(epub: zipfile.ZipFile, files: list[str]) -> list[Block]:
    blocks: list[Block] = []
    for file_index, name in enumerate(files):
        if name not in epub.namelist():
            continue
        soup = BeautifulSoup(epub.read(name), "lxml")
        block_index = 0
        for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]):
            text = clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            blocks.append(Block(file_index, name, block_index, node.name.lower(), text))
            block_index += 1
    return blocks


def nav_items(epub: zipfile.ZipFile, files: list[str], blocks: list[Block]) -> list[dict[str, str | int]]:
    ncx_name = next((n for n in epub.namelist() if n.lower().endswith(".ncx")), "")
    if not ncx_name:
        return []
    root = ET.fromstring(epub.read(ncx_name))
    file_map = {name: i for i, name in enumerate(files)}
    by_file: dict[str, list[Block]] = {}
    for block in blocks:
        by_file.setdefault(block.file_name, []).append(block)
    result = []
    for point in root.findall(".//n:navPoint", NCX_NS):
        label_node = point.find("n:navLabel/n:text", NCX_NS)
        content = point.find("n:content", NCX_NS)
        label = clean_text(label_node.text or "") if label_node is not None else ""
        src = content.attrib.get("src", "") if content is not None else ""
        src_file, _, fragment = urllib.parse.unquote(src).partition("#")
        nearby = by_file.get(src_file, [])
        context = " | ".join(x.text for x in nearby[:4])[:600]
        if fragment and src_file in epub.namelist():
            raw = epub.read(src_file).decode("utf-8", errors="replace")
            match = re.search(rf"\bid\s*=\s*['\"]{re.escape(fragment)}['\"]", raw, re.IGNORECASE)
            if match:
                before = clean_text(BeautifulSoup(raw[: match.start()], "lxml").get_text(" ", strip=True))
                after = clean_text(BeautifulSoup(raw[match.start() :], "lxml").get_text(" ", strip=True))
                context = (before[-180:] + " >> " + after[:420]).strip()
        result.append({
            "label": label,
            "src": src,
            "file_index": file_map.get(src_file, -1),
            "context": context,
        })
    return result


def context_window(blocks: list[Block], center: int, before: int = 2, after: int = 4) -> str:
    selected = blocks[max(0, center - before) : center + after + 1]
    return " | ".join(block.text for block in selected)[:1000]


def printed_toc_windows(blocks: list[Block]) -> list[tuple[Block, str]]:
    hits: list[tuple[Block, str]] = []
    for i, block in enumerate(blocks):
        if TOC_RE.search(block.text) and len(block.text) <= 80:
            selected: list[Block] = []
            prose_run = 0
            for candidate in blocks[i : i + 500]:
                selected.append(candidate)
                looks_like_prose = (
                    len(candidate.text) > 260
                    and not PAGE_SUFFIX_RE.search(candidate.text)
                    and not CHAPTER_RE.search(candidate.text[:80])
                )
                prose_run = prose_run + 1 if looks_like_prose else 0
                if len(selected) >= 12 and prose_run >= 3:
                    selected = selected[:-3]
                    break
            text = "\n".join(
                f"[f{x.file_index}:{x.block_index}:{x.tag}] {x.text}" for x in selected
            )
            hits.append((block, text[:30000]))
    return hits[:8]


def structural_hits(blocks: list[Block]) -> list[tuple[Block, str]]:
    hits: list[tuple[Block, str]] = []
    for i, block in enumerate(blocks):
        text = block.text
        explicit_heading = block.tag.startswith("h")
        structural = CHAPTER_RE.search(text) and len(text) <= 180
        named_frontmatter = len(text) <= 40 and text in {
            "序", "序言", "前言", "引言", "导言", "绪论", "后记", "结语", "尾声",
            "致谢", "参考文献", "参考资料", "附录", "索引",
        }
        if explicit_heading or structural or named_frontmatter:
            if PAGE_ONLY_RE.fullmatch(text):
                continue
            hits.append((block, context_window(blocks, i, 1, 2)))
    return hits


def probable_toc_line_count(blocks: list[Block]) -> int:
    count = 0
    for block in blocks:
        if len(block.text) <= 200 and (PAGE_SUFFIX_RE.search(block.text) or CHAPTER_RE.search(block.text)):
            count += 1
    return count


def write_packet(epub_path: Path, output_dir: Path) -> dict[str, str | int]:
    with zipfile.ZipFile(epub_path) as epub:
        files = spine(epub)
        blocks = extract_blocks(epub, files)
        nav = nav_items(epub, files, blocks)
        toc_windows = printed_toc_windows(blocks)
        hits = structural_hits(blocks)

    lines = [
        f"# {epub_path.name}", "",
        f"- spine_files: {len(files)}",
        f"- text_blocks: {len(blocks)}",
        f"- current_nav_items: {len(nav)}",
        f"- printed_toc_windows: {len(toc_windows)}",
        f"- structural_hits: {len(hits)}", "",
        "## Current navigation", "",
    ]
    for i, item in enumerate(nav, 1):
        lines.append(f"{i}. {item['label']} -> `{item['src']}` (file {item['file_index']})")
        lines.append(f"   Context: {item['context']}")
    lines.extend(["", "## Printed TOC evidence", ""])
    if not toc_windows:
        lines.append("No explicit short '目录/Contents' block detected.")
    for i, (block, window) in enumerate(toc_windows, 1):
        lines.append(f"### Window {i}: `{block.file_name}` file {block.file_index}, block {block.block_index}")
        lines.append("")
        lines.append("```text")
        lines.append(window)
        lines.append("```")
    lines.extend(["", "## Structural occurrences in source order", ""])
    for i, (block, context) in enumerate(hits, 1):
        lines.append(
            f"{i}. file {block.file_index} `{block.file_name}` block {block.block_index} "
            f"`<{block.tag}>`: {block.text}"
        )
        lines.append(f"   Context: {context}")

    output_dir.mkdir(parents=True, exist_ok=True)
    report = output_dir / f"{epub_path.stem}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "name": epub_path.name,
        "spine_files": len(files),
        "text_blocks": len(blocks),
        "nav_items": len(nav),
        "toc_windows": len(toc_windows),
        "structural_hits": len(hits),
        "probable_toc_lines": probable_toc_line_count(blocks),
        "report": str(report),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    args = parser.parse_args()

    rows = [write_packet(path, args.output_dir) for path in sorted(args.input_dir.glob("*.epub"))]
    args.summary_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.summary_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["name"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} review packets to {args.output_dir}")
    print(f"Wrote {args.summary_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
