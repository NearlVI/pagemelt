#!/usr/bin/env python
"""Repair EPUB NCX entries that point at printed table-of-contents pages.

The tool keeps the reader TOC intact where possible:
- labels like "第1章 标题……12" are cleaned to "第1章 标题";
- their targets are moved to the later occurrence of the same title in body HTML;
- obvious long numbered body-list entries can be removed, but never if that would
  collapse the whole TOC.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
ET.register_namespace("", NCX_NS)

TAG_RE = re.compile(r"<[^>]+>")
PAGE_LOCATOR_RE = re.compile(r"\s*(?:[.\u00b7\uff0e\u3002\u2026]{2,}|/{1,2})\s*\d{1,4}\s*$")
BARE_PAGE_RE = re.compile(
    r"\s+\d{1,4}$"
)
CHAPTER_PREFIX_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]|\d{1,3}[.、]\s*|[一二三四五六七八九十]+[、.．]\s*)"
)
NUMBERED_BODY_RE = re.compile(r"^\d{1,3}[.、]\s*\S")
SENTENCE_PUNCT_RE = re.compile(r"[。？！；，：]")


@dataclass
class HtmlDoc:
    name: str
    text: str


def normalize_text(text: str) -> str:
    text = html.unescape(TAG_RE.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(text: str) -> str:
    text = normalize_text(text)
    text = PAGE_LOCATOR_RE.sub("", text)
    if CHAPTER_PREFIX_RE.match(text):
        text = BARE_PAGE_RE.sub("", text)
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[.．。·…/]+$", "", text)
    return text.strip()


def cleaned_label(text: str) -> str:
    text = normalize_text(text)
    text = PAGE_LOCATOR_RE.sub("", text)
    if CHAPTER_PREFIX_RE.match(text):
        text = BARE_PAGE_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" .．。·…/")


def looks_like_printed_toc_label(text: str) -> bool:
    text = normalize_text(text)
    if len(text) > 140:
        return False
    if PAGE_LOCATOR_RE.search(text):
        return True
    return bool(CHAPTER_PREFIX_RE.match(text) and BARE_PAGE_RE.search(text))


def looks_like_body_list_label(text: str) -> bool:
    text = normalize_text(text)
    if not NUMBERED_BODY_RE.match(text):
        return False
    return len(text) > 36 or bool(SENTENCE_PUNCT_RE.search(text))


def split_src(src: str) -> tuple[str, str]:
    parsed = urllib.parse.urldefrag(src)
    return urllib.parse.unquote(parsed.url), urllib.parse.unquote(parsed.fragment)


def nav_label(nav_point: ET.Element) -> str:
    label = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
    return normalize_text(label.text or "") if label is not None else ""


def set_nav_label(nav_point: ET.Element, text: str) -> None:
    label = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
    if label is not None:
        label.text = text


def nav_content(nav_point: ET.Element) -> ET.Element | None:
    return nav_point.find(f"{{{NCX_NS}}}content")


def html_order(infos: list[zipfile.ZipInfo]) -> list[str]:
    names = [
        info.filename
        for info in infos
        if Path(info.filename).suffix.lower() in HTML_EXTENSIONS
        and "titlepage" not in info.filename.lower()
    ]
    return sorted(names)


def find_body_target(
    docs: list[HtmlDoc],
    order: list[str],
    original_file: str,
    label: str,
) -> tuple[str, str, dict[str, str]] | None:
    key = normalize_key(label)
    if not key or len(key) < 4:
        return None

    start_index = order.index(original_file) + 1 if original_file in order else 0
    search_docs = docs[start_index:] + docs[:start_index]
    escaped = html.escape(cleaned_label(label), quote=False)
    raw = cleaned_label(label)
    candidates = [escaped, raw]

    for doc in search_docs:
        for needle in candidates:
            if not needle:
                continue
            idx = doc.text.find(needle)
            if idx >= 0:
                anchor_id = "tocfix_" + str(abs(hash((doc.name, key, idx))) % 10_000_000)
                updated = doc.text[:idx] + f'<a id="{anchor_id}"></a>' + doc.text[idx:]
                return doc.name, anchor_id, {doc.name: updated}

    # Fallback: compare normalized plain text per paragraph/heading.
    block_re = re.compile(r"<(?P<tag>p|h[1-6]|strong)\b[^>]*>(?P<body>.*?)</(?P=tag)>", re.I | re.S)
    for doc in search_docs:
        for match in block_re.finditer(doc.text):
            body_key = normalize_key(match.group("body"))
            if key and (key in body_key or body_key in key):
                anchor_id = "tocfix_" + str(abs(hash((doc.name, key, match.start()))) % 10_000_000)
                updated = doc.text[: match.start()] + f'<a id="{anchor_id}"></a>' + doc.text[match.start() :]
                return doc.name, anchor_id, {doc.name: updated}
    return None


def prune_navpoints(nav_map: ET.Element, remove: set[ET.Element]) -> int:
    removed = 0
    for child in list(nav_map):
        if child.tag != f"{{{NCX_NS}}}navPoint":
            continue
        removed += prune_navpoints(child, remove)
        if child in remove:
            nav_map.remove(child)
            removed += 1
    return removed


def renumber_navpoints(root: ET.Element) -> None:
    for index, nav_point in enumerate(root.iter(f"{{{NCX_NS}}}navPoint"), start=1):
        nav_point.set("playOrder", str(index))


def iter_epubs(paths: list[Path]) -> list[Path]:
    epubs: list[Path] = []
    for path in paths:
        if path.is_dir():
            epubs.extend(sorted(path.glob("*.epub")))
        elif path.suffix.lower() == ".epub":
            epubs.append(path)
    return epubs


def write_entry(dst: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> None:
    new_info = zipfile.ZipInfo(info.filename, info.date_time)
    new_info.comment = info.comment
    new_info.extra = info.extra
    new_info.internal_attr = info.internal_attr
    new_info.external_attr = info.external_attr
    new_info.create_system = info.create_system
    new_info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
    dst.writestr(new_info, data)


def repair_epub(path: Path, apply: bool) -> tuple[int, int, int]:
    html_updates: dict[str, str] = {}
    relinked = 0
    label_cleaned = 0
    removed = 0

    with zipfile.ZipFile(path, "r") as src:
        infos = src.infolist()
        order = html_order(infos)
        docs = [
            HtmlDoc(name, src.read(name).decode("utf-8", errors="replace"))
            for name in order
        ]
        ncx_infos = [info for info in infos if Path(info.filename).suffix.lower() == ".ncx"]
        if not ncx_infos:
            return 0, 0, 0

        ncx_data = src.read(ncx_infos[0].filename)
        root = ET.fromstring(ncx_data)
        nav_map = root.find(f"{{{NCX_NS}}}navMap")
        if nav_map is None:
            return 0, 0, 0
        nav_points = list(root.iter(f"{{{NCX_NS}}}navPoint"))
        remove_candidates: set[ET.Element] = set()

        for nav_point in nav_points:
            label = nav_label(nav_point)
            content = nav_content(nav_point)
            if content is None:
                continue
            file_name, _fragment = split_src(content.attrib.get("src", ""))

            if looks_like_printed_toc_label(label):
                clean = cleaned_label(label)
                if clean and clean != label:
                    set_nav_label(nav_point, clean)
                    label_cleaned += 1
                target = find_body_target(
                    [
                        HtmlDoc(doc.name, html_updates.get(doc.name, doc.text))
                        for doc in docs
                    ],
                    order,
                    file_name,
                    clean or label,
                )
                if target is not None:
                    target_file, anchor_id, updates = target
                    html_updates.update(updates)
                    content.set("src", f"{target_file}#{anchor_id}")
                    relinked += 1
            elif looks_like_body_list_label(label):
                remove_candidates.add(nav_point)

        remaining = len(nav_points) - len(remove_candidates)
        if remaining >= 3:
            removed = prune_navpoints(nav_map, remove_candidates)
        renumber_navpoints(root)
        ncx_updated = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        if not apply:
            return relinked, label_cleaned, removed

        fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".epub", dir=str(path.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with zipfile.ZipFile(temp_path, "w") as dst:
                mimetype = next((info for info in infos if info.filename == "mimetype"), None)
                ordered = ([mimetype] if mimetype else []) + [info for info in infos if info is not mimetype]
                for info in ordered:
                    if info.filename == ncx_infos[0].filename:
                        data = ncx_updated
                    elif info.filename in html_updates:
                        data = html_updates[info.filename].encode("utf-8")
                    else:
                        data = src.read(info.filename)
                    write_entry(dst, info, data)
            shutil.move(str(temp_path), str(path))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    return relinked, label_cleaned, removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changed = 0
    total_relinked = 0
    total_cleaned = 0
    total_removed = 0
    for epub in iter_epubs(args.paths):
        relinked, cleaned, removed = repair_epub(epub, args.apply)
        if relinked or cleaned or removed:
            changed += 1
            total_relinked += relinked
            total_cleaned += cleaned
            total_removed += removed
            action = "fixed" if args.apply else "would fix"
            print(f"{epub.name}: {action}; relinked={relinked}; cleaned_labels={cleaned}; removed_body_items={removed}")
    print(
        "Changed EPUBs: "
        f"{changed}; relinked: {total_relinked}; cleaned labels: {total_cleaned}; "
        f"removed body-list nav entries: {total_removed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
