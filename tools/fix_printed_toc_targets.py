#!/usr/bin/env python
"""Remove or relink NCX entries that point to printed table-of-contents blocks."""

from __future__ import annotations

import argparse
import html
import os
import posixpath
import re
import shutil
import tempfile
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
ET.register_namespace("", NCX_NS)

HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}
TAG_RE = re.compile(r"<[^>]+>")
PAGE_LOCATOR_RE = re.compile(r"(?:[.\u00b7\uff0e\u3002\u2026_]{2,}|/{1,2})\s*\d{1,4}")
PAGE_LOCATOR_AFTER_RE = re.compile(
    r"^\s*(?:[.\u00b7\uff0e\u3002\u2026_]{1,}|/{1,2})\s*\d{1,4}(?:\s|$)"
)
LEADING_PAGE_RE = re.compile(r"(?:^|\s)\d{1,4}\s+[\u4e00-\u9fffA-Za-z]")
ID_RE_TEMPLATE = r"\bid\s*=\s*['\"]{}['\"]"
ORDINAL_RE = re.compile(
    r"^\s*(第\s*[一二三四五六七八九十百零〇\d]+\s*[章节讲篇部卷]|"
    r"[一二三四五六七八九十百零〇]+[、.．]|"
    r"\d{1,3}[、.．])"
)


@dataclass
class HtmlDoc:
    name: str
    text: str


@dataclass
class NavInfo:
    element: ET.Element
    label: str
    src: str
    file_name: str
    fragment: str
    file_index: int
    offset: int
    position: int
    snippet: str
    printed_like: bool


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text))).strip()


def normalize_key(text: str) -> str:
    text = clean_label(text)
    text = re.sub(r"[\s\u3000,，.．。:：;；/／_—\-]+", "", text)
    return text.strip()


def clean_label(text: str) -> str:
    text = normalize_text(text)
    text = PAGE_LOCATOR_RE.sub("", text)
    text = re.sub(r"\s+\d{1,4}$", "", text)
    text = text.strip(" .．。·…_")
    return re.sub(r"\s+", " ", text)


def ordinal_prefix(text: str) -> str:
    match = ORDINAL_RE.match(clean_label(text))
    return re.sub(r"\s+", "", match.group(1)) if match else ""


def decode_href(href: str, base: str = "") -> str:
    href = urllib.parse.unquote(href)
    if base:
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    return href


def split_src(src: str) -> tuple[str, str]:
    base, frag = urllib.parse.urldefrag(src)
    return urllib.parse.unquote(base), urllib.parse.unquote(frag)


def get_opf_path(epub: zipfile.ZipFile) -> str:
    root = ET.fromstring(epub.read("META-INF/container.xml"))
    rootfile = root.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is not None:
        return rootfile.attrib["full-path"]
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
    return ordered


def ncx_name(epub: zipfile.ZipFile) -> str | None:
    return next((name for name in epub.namelist() if name.lower().endswith(".ncx")), None)


def nav_label(nav_point: ET.Element) -> str:
    label = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
    return normalize_text(label.text or "") if label is not None else ""


def set_nav_label(nav_point: ET.Element, text: str) -> None:
    label = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
    if label is not None:
        label.text = text


def nav_src(nav_point: ET.Element) -> str:
    content = nav_point.find(f"{{{NCX_NS}}}content")
    return content.attrib.get("src", "") if content is not None else ""


def set_nav_src(nav_point: ET.Element, src: str) -> None:
    content = nav_point.find(f"{{{NCX_NS}}}content")
    if content is not None:
        content.set("src", src)


def find_fragment_offset(text: str, fragment: str, label: str) -> int:
    if fragment:
        match = re.search(ID_RE_TEMPLATE.format(re.escape(fragment)), text)
        if match:
            return match.start()
    raw = clean_label(label)
    for needle in [raw, html.escape(raw, quote=False)]:
        if needle:
            idx = text.find(needle)
            if idx >= 0:
                return idx
    return 0


def snippet_for(text: str, offset: int) -> str:
    return normalize_text(text[max(0, offset - 500) : offset + 900])


def looks_like_printed_toc(snippet: str) -> bool:
    head = snippet[:700]
    locator_count = len(PAGE_LOCATOR_RE.findall(head))
    leading_page_count = len(LEADING_PAGE_RE.findall(head))
    has_toc = "目录" in head or "Contents" in head
    return (has_toc and (locator_count >= 1 or leading_page_count >= 3)) or locator_count >= 2


def has_locator_near(text: str, start: int, end: int) -> bool:
    context = normalize_text(text[max(0, start - 40) : end + 160])
    return bool(PAGE_LOCATOR_RE.search(context) or LEADING_PAGE_RE.search(context))


def has_next_label_near(text: str, end: int, next_label: str) -> bool:
    if not next_label:
        return False
    next_key = normalize_key(next_label)
    if len(next_key) < 3:
        return False
    context_key = normalize_key(text[end : end + 360])
    return next_key in context_key


def nav_infos(root: ET.Element, spine: list[str], docs: dict[str, HtmlDoc]) -> list[NavInfo]:
    index = {name: i for i, name in enumerate(spine)}
    infos: list[NavInfo] = []
    for nav_point in root.iter(f"{{{NCX_NS}}}navPoint"):
        label = nav_label(nav_point)
        src = nav_src(nav_point)
        file_name, fragment = split_src(src)
        file_index = index.get(file_name, -1)
        doc = docs.get(file_name)
        offset = find_fragment_offset(doc.text, fragment, label) if doc else -1
        position = file_index * 1_000_000_000 + max(offset, 0) if file_index >= 0 else -1
        snippet = snippet_for(doc.text, max(offset, 0)) if doc else ""
        infos.append(
            NavInfo(
                nav_point,
                label,
                src,
                file_name,
                fragment,
                file_index,
                offset,
                position,
                snippet,
                looks_like_printed_toc(snippet),
            )
        )
    return infos


def has_later_duplicate(info: NavInfo, infos: list[NavInfo]) -> bool:
    key = normalize_key(info.label)
    ordinal = ordinal_prefix(info.label)
    for later in infos:
        if later.position <= info.position:
            continue
        later_key = normalize_key(later.label)
        if key and later_key and (key == later_key or key in later_key or later_key in key):
            return True
        if ordinal and ordinal_prefix(later.label) == ordinal:
            return True
    return False


def find_later_body_target(
    docs: list[HtmlDoc],
    spine: list[str],
    info: NavInfo,
    label: str,
    anchor_id: str,
    next_label: str = "",
) -> tuple[str, str] | None:
    clean = clean_label(label)
    candidates = [clean, re.sub(r"^第\s*[一二三四五六七八九十百零〇\d]+\s*[章节讲篇部卷]\s*", "", clean)]
    candidates.extend(html.escape(candidate, quote=False) for candidate in list(candidates))
    start_position = info.position

    for file_index, doc in enumerate(docs):
        base_position = file_index * 1_000_000_000
        start = max(0, info.offset + 1) if doc.name == info.file_name else 0
        if base_position + len(doc.text) <= start_position:
            continue
        for candidate in candidates:
            if not candidate or len(normalize_key(candidate)) < 2:
                continue
            search = start
            while True:
                idx = doc.text.find(candidate, search)
                if idx < 0:
                    break
                search = idx + len(candidate)
                if base_position + idx <= start_position:
                    continue
                if has_locator_near(doc.text, idx, idx + len(candidate)):
                    continue
                if has_next_label_near(doc.text, idx + len(candidate), next_label):
                    continue
                updated = doc.text[:idx] + f'<a id="{anchor_id}"></a>' + doc.text[idx:]
                return doc.name, updated

        key = normalize_key(clean)
        if len(key) < 4:
            continue
        block_re = re.compile(r"<(?P<tag>p|h[1-6]|strong)\b[^>]*>.*?</(?P=tag)>", re.I | re.S)
        for match in block_re.finditer(doc.text, pos=start):
            if base_position + match.start() <= start_position:
                continue
            if has_locator_near(doc.text, match.start(), match.end()):
                continue
            if has_next_label_near(doc.text, match.end(), next_label):
                continue
            block_key = normalize_key(match.group(0))
            if key in block_key or block_key in key:
                updated = doc.text[: match.start()] + f'<a id="{anchor_id}"></a>' + doc.text[match.start() :]
                return doc.name, updated
    return None


def remove_navpoint(parent: ET.Element, target: ET.Element) -> bool:
    for child in list(parent):
        if child is target:
            parent.remove(child)
            return True
        if remove_navpoint(child, target):
            return True
    return False


def renumber(root: ET.Element) -> None:
    for index, nav_point in enumerate(root.iter(f"{{{NCX_NS}}}navPoint"), start=1):
        nav_point.set("playOrder", str(index))


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
    removed = 0
    relinked = 0
    labels_cleaned = 0

    with zipfile.ZipFile(path, "r") as src:
        infos = src.infolist()
        spine = html_spine(src)
        docs_list = [
            HtmlDoc(name, src.read(name).decode("utf-8", errors="replace"))
            for name in spine
            if name in src.namelist()
        ]
        docs = {doc.name: doc for doc in docs_list}
        ncx = ncx_name(src)
        if not ncx:
            return 0, 0, 0
        root = ET.fromstring(src.read(ncx))
        nav_map = root.find(f"{{{NCX_NS}}}navMap")
        if nav_map is None:
            return 0, 0, 0

        infos_before = nav_infos(root, spine, docs)
        updates: dict[str, str] = {}
        to_remove: list[ET.Element] = []

        for index, info in enumerate(infos_before, start=1):
            if not info.printed_like:
                continue
            clean = clean_label(info.label)
            if clean in {"目录", "Contents"} or has_later_duplicate(info, infos_before):
                to_remove.append(info.element)
                continue

            anchor_id = f"tocbody_{index}"
            current_docs = [
                HtmlDoc(doc.name, updates.get(doc.name, doc.text))
                for doc in docs_list
            ]
            next_label = infos_before[index].label if index < len(infos_before) else ""
            target = find_later_body_target(current_docs, spine, info, clean, anchor_id, next_label)
            if target is None:
                continue
            target_file, updated_text = target
            updates[target_file] = updated_text
            set_nav_src(info.element, f"{target_file}#{anchor_id}")
            if clean and clean != info.label:
                set_nav_label(info.element, clean)
                labels_cleaned += 1
            relinked += 1

        remaining = len(infos_before) - len(to_remove)
        if remaining >= 2:
            for element in to_remove:
                if remove_navpoint(nav_map, element):
                    removed += 1
        renumber(root)
        ncx_data = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        if not apply:
            return removed, relinked, labels_cleaned

        fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".epub", dir=str(path.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with zipfile.ZipFile(temp_path, "w") as dst:
                mimetype = next((info for info in infos if info.filename == "mimetype"), None)
                ordered = ([mimetype] if mimetype else []) + [info for info in infos if info is not mimetype]
                for info in ordered:
                    if info.filename == ncx:
                        data = ncx_data
                    elif info.filename in updates:
                        data = updates[info.filename].encode("utf-8")
                    else:
                        data = src.read(info.filename)
                    write_entry(dst, info, data)
            shutil.move(str(temp_path), str(path))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    return removed, relinked, labels_cleaned


def iter_epubs(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob("*.epub"))
    return [path]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    total_removed = total_relinked = total_cleaned = books = 0
    for epub in iter_epubs(args.path):
        removed, relinked, cleaned = repair_epub(epub, args.apply)
        if removed or relinked or cleaned:
            action = "fixed" if args.apply else "would fix"
            print(
                f"{epub.name}: {action}; removed={removed} relinked={relinked} labels_cleaned={cleaned}"
            )
            books += 1
            total_removed += removed
            total_relinked += relinked
            total_cleaned += cleaned
    print(
        f"Books affected: {books}; removed={total_removed}; "
        f"relinked={total_relinked}; labels_cleaned={total_cleaned}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
