#!/usr/bin/env python
"""Apply a reviewed TOC specification to EPUB NCX files."""

from __future__ import annotations

import argparse
import html
import json
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
from typing import Any


CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
ET.register_namespace("", NCX_NS)

HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}
TAG_RE = re.compile(r"<[^>]+>")
PRINTED_LOCATOR_AFTER_RE = re.compile(
    r"^\s*(?:[.\u00b7\uff0e\u3002\u2026_]{2,}|/{1,2})\s*\d{1,4}(?:\s|$)"
)
PRINTED_LOCATOR_ANY_RE = re.compile(
    r"(?:[.\u00b7\uff0e\u3002\u2026_]{2,}|/{1,2})\s*\d{1,4}(?:\s|$)"
)
PRINTED_LOCATOR_BEFORE_RE = re.compile(r"(?:^|\s)\d{1,4}\s*$")


@dataclass
class HtmlDoc:
    name: str
    text: str
    plain: str


def normalize_text(text: str) -> str:
    text = html.unescape(TAG_RE.sub(" ", text))
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\s*(?:[.\u00b7\uff0e\u3002\u2026]{2,}|/{1,2})\s*\d{1,4}\s*$", "", text)
    text = re.sub(r"[_\s\u3000,，.。:：;；/、·．…!！?？-]+", "", text)
    return text.strip()


def has_printed_locator_after(text: str, end_idx: int) -> bool:
    """Return True when a match is followed by TOC leader dots and a page number."""
    tail = html.unescape(TAG_RE.sub(" ", text[end_idx : end_idx + 120]))
    return bool(PRINTED_LOCATOR_AFTER_RE.match(tail))


def has_printed_locator_before(text: str, start_idx: int) -> bool:
    """Return True when a match is immediately preceded by a printed TOC page number."""
    head = html.unescape(TAG_RE.sub(" ", text[max(0, start_idx - 30) : start_idx]))
    return bool(PRINTED_LOCATOR_BEFORE_RE.search(head))


def has_printed_locator_near(text: str, start_idx: int, end_idx: int) -> bool:
    """Return True when a matched heading tag is part of a printed TOC run."""
    context = html.unescape(TAG_RE.sub(" ", text[start_idx : end_idx + 140]))
    return bool(PRINTED_LOCATOR_ANY_RE.search(context))


def decode_href(href: str, base: str = "") -> str:
    href = urllib.parse.unquote(href)
    if base:
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    return href


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


def load_docs(epub: zipfile.ZipFile) -> list[HtmlDoc]:
    docs: list[HtmlDoc] = []
    for name in html_spine(epub):
        if name not in epub.namelist():
            continue
        text = epub.read(name).decode("utf-8", errors="replace")
        docs.append(HtmlDoc(name, text, normalize_text(text)))
    return docs


def insert_anchor(text: str, search: str, anchor_id: str, occurrence: int) -> tuple[str, bool]:
    candidates = [html.escape(search, quote=False), search]
    for candidate in candidates:
        if not candidate:
            continue
        start = 0
        accepted = 0
        while True:
            idx = text.find(candidate, start)
            if idx < 0:
                break
            start = idx + len(candidate)
            if has_printed_locator_before(text, idx) or has_printed_locator_after(text, idx + len(candidate)):
                continue
            accepted += 1
            if accepted >= max(1, occurrence):
                return text[:idx] + f'<a id="{anchor_id}"></a>' + text[idx:], True
    key = normalize_key(search)
    if not key:
        return text, False
    matches: list[int] = []
    for tag_match in re.finditer(r"<(?P<tag>p|h[1-6]|strong)\b[^>]*>.*?</(?P=tag)>", text, re.I | re.S):
        if (
            key in normalize_key(tag_match.group(0))
            and not has_printed_locator_before(text, tag_match.start())
            and not has_printed_locator_after(text, tag_match.end())
            and not has_printed_locator_near(text, tag_match.start(), tag_match.end())
        ):
            matches.append(tag_match.start())
    if len(matches) >= max(1, occurrence):
        idx = matches[max(1, occurrence) - 1]
        return text[:idx] + f'<a id="{anchor_id}"></a>' + text[idx:], True
    return text, False


def find_doc_for_search(docs: list[HtmlDoc], search: str, start_index: int) -> tuple[int, int]:
    key = normalize_key(search)
    for offset in range(start_index, len(docs)):
        if key and key in normalize_key(docs[offset].plain):
            return offset, 1
    for offset in range(0, start_index):
        if key and key in normalize_key(docs[offset].plain):
            return offset, 1
    raise ValueError(f"Could not find TOC search text: {search}")


def candidate_doc_indexes(docs: list[HtmlDoc], search: str, start_index: int) -> list[int]:
    key = normalize_key(search)
    if not key:
        return []
    ordered = list(range(start_index, len(docs))) + list(range(0, start_index))
    return [index for index in ordered if key in normalize_key(docs[index].plain)]


def ncx_path(epub: zipfile.ZipFile) -> str:
    for name in epub.namelist():
        if name.lower().endswith(".ncx"):
            return name
    raise ValueError("No NCX file found")


def build_nav_map(entries: list[dict[str, Any]]) -> ET.Element:
    nav_map = ET.Element(f"{{{NCX_NS}}}navMap")

    def add_entries(parent: ET.Element, items: list[dict[str, Any]], counter: list[int]) -> None:
        for item in items:
            attrs = {"id": f"manual_toc_{counter[0]}", "playOrder": str(counter[0])}
            counter[0] += 1
            nav_point = ET.SubElement(parent, f"{{{NCX_NS}}}navPoint", attrs)
            nav_label = ET.SubElement(nav_point, f"{{{NCX_NS}}}navLabel")
            text_el = ET.SubElement(nav_label, f"{{{NCX_NS}}}text")
            text_el.text = item["label"]
            ET.SubElement(nav_point, f"{{{NCX_NS}}}content", {"src": item["src"]})
            children = item.get("children") or []
            add_entries(nav_point, children, counter)

    add_entries(nav_map, entries, [1])
    return nav_map


def replace_nav_map(ncx_data: bytes, entries: list[dict[str, Any]]) -> bytes:
    root = ET.fromstring(ncx_data)
    old = root.find(f"{{{NCX_NS}}}navMap")
    if old is not None:
        root.remove(old)
    root.append(build_nav_map(entries))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def flatten_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for entry in entries:
        flat.append(entry)
        flat.extend(flatten_entries(entry.get("children") or []))
    return flat


def write_entry(dst: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> None:
    new_info = zipfile.ZipInfo(info.filename, info.date_time)
    new_info.comment = info.comment
    new_info.extra = info.extra
    new_info.internal_attr = info.internal_attr
    new_info.external_attr = info.external_attr
    new_info.create_system = info.create_system
    new_info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
    dst.writestr(new_info, data)


def apply_spec(epub_path: Path, spec: dict[str, Any], dry_run: bool) -> int:
    with zipfile.ZipFile(epub_path, "r") as src:
        infos = src.infolist()
        docs = load_docs(src)
        doc_updates = {doc.name: doc.text for doc in docs}
        flat = flatten_entries(spec["entries"])

        for index, entry in enumerate(flat, start=1):
            search = entry.get("search") or entry["label"]
            anchor_search = entry.get("search_html") or search
            start_index = int(entry.get("start_index", 0))
            occurrence = int(entry.get("occurrence", 1))
            anchor_id = f"manual_toc_{index}"
            for doc_index in candidate_doc_indexes(docs, search, start_index):
                updated, ok = insert_anchor(
                    doc_updates[docs[doc_index].name], anchor_search, anchor_id, occurrence
                )
                if ok:
                    doc_updates[docs[doc_index].name] = updated
                    entry["src"] = f"{docs[doc_index].name}#{anchor_id}"
                    break
            else:
                raise ValueError(f"Could not anchor {entry['label']} in {epub_path.name}")

        ncx_name = ncx_path(src)
        ncx_data = replace_nav_map(src.read(ncx_name), spec["entries"])

        if dry_run:
            return len(flat)

        fd, temp_name = tempfile.mkstemp(prefix=epub_path.stem + ".", suffix=".epub", dir=str(epub_path.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with zipfile.ZipFile(temp_path, "w") as dst:
                mimetype = next((info for info in infos if info.filename == "mimetype"), None)
                ordered = ([mimetype] if mimetype else []) + [info for info in infos if info is not mimetype]
                for info in ordered:
                    if info.filename == ncx_name:
                        data = ncx_data
                    elif info.filename in doc_updates:
                        data = doc_updates[info.filename].encode("utf-8")
                    else:
                        data = src.read(info.filename)
                    write_entry(dst, info, data)
            shutil.move(str(temp_path), str(epub_path))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    return len(flat)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epub-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--only-file", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    specs = json.loads(args.spec.read_text(encoding="utf-8"))
    applied = 0
    for spec in specs["books"]:
        if args.only_file and spec["file"] not in set(args.only_file):
            continue
        matches = list(args.epub_dir.glob(spec["file"]))
        if len(matches) != 1:
            raise ValueError(f"Expected one EPUB for {spec['file']}, found {len(matches)}")
        count = apply_spec(matches[0], spec, dry_run=not args.apply)
        applied += 1
        action = "fixed" if args.apply else "would fix"
        print(f"{matches[0].name}: {action}; toc_entries={count}")
    print(f"Books processed: {applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
