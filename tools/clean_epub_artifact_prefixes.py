#!/usr/bin/env python
"""Remove leaked MinerU block labels from EPUB body HTML."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


HTML_EXTENSIONS = {".html", ".xhtml", ".htm"}
TAG_ARTIFACT_RE = re.compile(
    r"(<(?:li|p|h[1-6])\b[^>]*>\s*)(?:text|paragraph)\b(?:\s*[-:：·●◎◆■]\s*|\s+)",
    re.IGNORECASE,
)


def clean_html(data: bytes) -> tuple[bytes, int]:
    text = data.decode("utf-8", errors="replace")
    cleaned, count = TAG_ARTIFACT_RE.subn(r"\1", text)
    if count == 0:
        return data, 0
    return cleaned.encode("utf-8"), count


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


def clean_epub(path: Path) -> int:
    total = 0
    fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".epub", dir=str(path.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(path, "r") as src, zipfile.ZipFile(temp_path, "w") as dst:
            infos = src.infolist()
            mimetype = next((info for info in infos if info.filename == "mimetype"), None)
            ordered = ([mimetype] if mimetype else []) + [info for info in infos if info is not mimetype]
            for info in ordered:
                data = src.read(info.filename)
                if Path(info.filename).suffix.lower() in HTML_EXTENSIONS:
                    data, count = clean_html(data)
                    total += count
                write_entry(dst, info, data)
        if total:
            shutil.move(str(temp_path), str(path))
        else:
            temp_path.unlink(missing_ok=True)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    changed = 0
    replacements = 0
    for epub in iter_epubs(args.paths):
        count = clean_epub(epub)
        if count:
            changed += 1
            replacements += count
            print(f"{epub.name}: removed {count} artifact prefixes")
    print(f"Changed EPUBs: {changed}; removed prefixes: {replacements}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
