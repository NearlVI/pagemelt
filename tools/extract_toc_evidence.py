#!/usr/bin/env python
"""Extract compact TOC evidence from EPUB files for manual/LLM review."""

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


CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}

HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}
TAG_RE = re.compile(r"<[^>]+>")
HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
ID_TAG_RE = re.compile(
    r"<(?P<tag>[a-zA-Z][\w:-]*)\b(?P<attrs>[^>]*\bid\s*=\s*['\"](?P<id>[^'\"]+)['\"][^>]*)>",
    re.IGNORECASE,
)
PAGE_LOCATOR_RE = re.compile(r"(?:[.\u00b7\uff0e\u3002\u2026]{2,}|/{1,2})\s*\d{1,4}\s*$")
BARE_PAGE_RE = re.compile(r"\s+\d{1,4}$")
CHAPTER_LINE_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]\s*.+|"
    r"[上下中][篇部卷]\s*[:：]?.+|"
    r"第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]\s*$|"
    r"\d{1,2}[.、]\s*[^\s].{2,60}"
    r")$"
)
BODY_NUMBERED_NOISE_RE = re.compile(r"^\d{1,3}[.、]\s*.+[。？！；，：]")


@dataclass
class HtmlItem:
    name: str
    text: str
    plain: str
    lines: list[str]


@dataclass
class NavItem:
    label: str
    src: str
    file_name: str
    fragment: str
    file_index: int
    snippet: str
    likely_printed_toc: bool


def normalize_text(text: str) -> str:
    text = html.unescape(TAG_RE.sub(" ", text))
    return re.sub(r"\s+", " ", text).strip()


def clean_label(text: str) -> str:
    text = normalize_text(text)
    text = PAGE_LOCATOR_RE.sub("", text)
    if re.match(r"^(?:第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]|\d{1,3}[.、]\s*)", text):
        text = BARE_PAGE_RE.sub("", text)
    return text.strip(" .．。·…/")


def normalize_key(text: str) -> str:
    text = clean_label(text)
    return re.sub(r"[\s\u3000,，.。:：;；/、·．…!！?？]+", "", text)


def decode_href(href: str, base: str = "") -> str:
    href = urllib.parse.unquote(href)
    if base:
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    return href


def split_src(src: str) -> tuple[str, str]:
    base, fragment = urllib.parse.urldefrag(src)
    return urllib.parse.unquote(base), urllib.parse.unquote(fragment)


def get_opf_path(epub: zipfile.ZipFile) -> str:
    try:
        root = ET.fromstring(epub.read("META-INF/container.xml"))
        rootfile = root.find(".//c:rootfile", CONTAINER_NS)
        if rootfile is not None:
            return rootfile.attrib["full-path"]
    except Exception:
        pass
    for name in epub.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ValueError("No OPF file found")


def html_spine(epub: zipfile.ZipFile) -> list[str]:
    opf_path = get_opf_path(epub)
    opf_root = ET.fromstring(epub.read(opf_path))
    manifest: dict[str, str] = {}
    for item in opf_root.findall(".//opf:manifest/opf:item", OPF_NS):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = decode_href(href, opf_path)
    ordered: list[str] = []
    for itemref in opf_root.findall(".//opf:spine/opf:itemref", OPF_NS):
        href = manifest.get(itemref.attrib.get("idref", ""))
        if href and Path(href).suffix.lower() in HTML_EXTENSIONS:
            ordered.append(href)
    if ordered:
        return ordered
    return [
        name
        for name in epub.namelist()
        if Path(name).suffix.lower() in HTML_EXTENSIONS and "titlepage" not in name.lower()
    ]


def load_html_items(epub: zipfile.ZipFile) -> list[HtmlItem]:
    items: list[HtmlItem] = []
    for name in html_spine(epub):
        if name not in epub.namelist():
            continue
        text = epub.read(name).decode("utf-8", errors="replace")
        plain = normalize_text(text)
        lines = [line.strip() for line in re.split(r"[\n\r]+", normalize_text(text).replace("。", "。\n")) if line.strip()]
        items.append(HtmlItem(name, text, plain, lines))
    return items


def snippet_for(item: HtmlItem, fragment: str, label: str) -> str:
    idx = -1
    if fragment:
        match = re.search(rf"\bid\s*=\s*['\"]{re.escape(fragment)}['\"]", item.text)
        if match:
            idx = match.start()
            plain_before = normalize_text(item.text[:idx])
            plain_text = item.plain
            plain_idx = min(len(plain_before), len(plain_text))
            return plain_text[max(0, plain_idx - 80) : plain_idx + 220]
    key = clean_label(label)
    if key:
        idx = item.plain.find(key)
    if idx < 0:
        idx = 0
    return item.plain[max(0, idx - 80) : idx + 220]


def extract_nav(epub: zipfile.ZipFile, items: list[HtmlItem]) -> list[NavItem]:
    names = epub.namelist()
    ncx_name = next((name for name in names if name.lower().endswith(".ncx")), "")
    if not ncx_name:
        return []
    doc = ET.fromstring(epub.read(ncx_name))
    index = {item.name: i for i, item in enumerate(items)}
    item_by_name = {item.name: item for item in items}
    nav: list[NavItem] = []
    for nav_point in doc.findall(".//n:navPoint", NCX_NS):
        label_el = nav_point.find("n:navLabel/n:text", NCX_NS)
        content_el = nav_point.find("n:content", NCX_NS)
        label = normalize_text(label_el.text or "") if label_el is not None else ""
        src = content_el.attrib.get("src", "") if content_el is not None else ""
        file_name, fragment = split_src(src)
        item = item_by_name.get(file_name)
        snippet = snippet_for(item, fragment, label) if item else ""
        file_index = index.get(file_name, -1)
        likely_printed = bool(PAGE_LOCATOR_RE.search(label)) or (
            file_index <= 2 and ("目录" in snippet[:120] or PAGE_LOCATOR_RE.search(snippet[:220]) is not None)
        )
        nav.append(NavItem(label, src, file_name, fragment, file_index, snippet, likely_printed))
    return nav


def body_heading_candidates(items: list[HtmlItem], limit: int) -> list[tuple[str, int, str]]:
    candidates: list[tuple[str, int, str]] = []
    for i, item in enumerate(items):
        for match in HEADING_RE.finditer(item.text):
            label = normalize_text(match.group(2))
            if label and len(label) <= 90 and label not in {"目录"}:
                candidates.append((item.name, i, label))
                if len(candidates) >= limit:
                    return candidates
        for line in item.lines:
            if len(line) > 90 or PAGE_LOCATOR_RE.search(line) or BODY_NUMBERED_NOISE_RE.match(line):
                continue
            if CHAPTER_LINE_RE.match(line):
                candidates.append((item.name, i, line))
                if len(candidates) >= limit:
                    return candidates
    return candidates


def matching_later_candidates(nav: list[NavItem], items: list[HtmlItem], limit: int) -> list[tuple[str, str, str]]:
    matches: list[tuple[str, str, str]] = []
    for entry in nav:
        if not entry.likely_printed_toc:
            continue
        key = normalize_key(entry.label)
        if len(key) < 4:
            continue
        for item in items[max(0, entry.file_index + 1) :]:
            plain_key = normalize_key(item.plain[:4000])
            if key in plain_key:
                matches.append((entry.label, item.name, clean_label(entry.label)))
                break
        if len(matches) >= limit:
            break
    return matches


def write_book_report(epub_path: Path, out_dir: Path) -> dict[str, int | str]:
    with zipfile.ZipFile(epub_path) as epub:
        items = load_html_items(epub)
        nav = extract_nav(epub, items)
        printed = [entry for entry in nav if entry.likely_printed_toc]
        body_noise = [
            entry
            for entry in nav
            if re.match(r"^\d{1,3}[.、]\s*.+[。？！；，：]", entry.label)
        ]
        candidates = body_heading_candidates(items, 120)
        matches = matching_later_candidates(nav, items, 60)

    lines = [
        f"# {epub_path.name}",
        "",
        f"- EPUB 导航项：{len(nav)}",
        f"- 疑似印刷目录导航项：{len(printed)}",
        f"- 疑似正文数字列表导航项：{len(body_noise)}",
        f"- 正文标题候选：{len(candidates)}",
        "",
        "## 当前 EPUB 导航",
        "",
    ]
    for idx, entry in enumerate(nav[:160], start=1):
        flag = " [疑似印刷目录]" if entry.likely_printed_toc else ""
        lines.append(f"{idx}. {entry.label}{flag}")
        lines.append(f"   - src: `{entry.src}` file_index={entry.file_index}")
        if entry.snippet:
            lines.append(f"   - near: {entry.snippet[:260]}")
    if len(nav) > 160:
        lines.append(f"- ... 还有 {len(nav) - 160} 项")

    lines.extend(["", "## 可迁移匹配", ""])
    for old, target, clean in matches:
        lines.append(f"- `{old}` -> `{clean}` at `{target}`")

    lines.extend(["", "## 正文标题候选", ""])
    for file_name, index, label in candidates:
        lines.append(f"- `{file_name}` #{index}: {label}")

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / (epub_path.stem + ".md")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "name": epub_path.name,
        "nav_items": len(nav),
        "printed_nav": len(printed),
        "body_list_nav": len(body_noise),
        "body_candidates": len(candidates),
        "migration_matches": len(matches),
        "report": str(report_path),
    }


def iter_epubs(paths: list[Path]) -> list[Path]:
    epubs: list[Path] = []
    for path in paths:
        if path.is_dir():
            epubs.extend(sorted(path.glob("*.epub")))
        elif path.suffix.lower() == ".epub":
            epubs.append(path)
    return epubs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    args = parser.parse_args()

    rows = [write_book_report(epub, args.output_dir) for epub in iter_epubs(args.paths)]
    args.summary_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.summary_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "name",
                "nav_items",
                "printed_nav",
                "body_list_nav",
                "body_candidates",
                "migration_matches",
                "report",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} reports to {args.output_dir}")
    print(f"Wrote summary to {args.summary_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
