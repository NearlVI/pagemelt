#!/usr/bin/env python
"""Convert MinerU structured output into ebook-friendly Markdown."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


SKIP_TYPES = {
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_header",
    "page_footer",
    "page_aside_text",
}

IMAGE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}

STRUCTURAL_KEYS = {
    "type",
    "bbox",
    "page_idx",
    "page_id",
    "index",
    "id",
    "score",
    "text_level",
    "level",
}

ARTIFACT_PREFIX_RE = re.compile(
    r"(?mi)^\s*(?:text|paragraph)\s*(?:[-:：]\s*|\s+(?=(?:\d{1,4}\b|[\u4e00-\u9fff])))"
)
LIST_ARTIFACT_PREFIX_RE = re.compile(
    r"(?mi)^(\s*[-*+]\s+)(?:text|paragraph)\b(?:\s*[-:：·●◎◆■]\s*|\s+)"
)
LIST_ITEM_ARTIFACT_RE = re.compile(
    r"(?i)^(?:text|paragraph)\b(?:\s*[-:：·●◎◆■]\s*|\s+)"
)
PRINTED_TOC_LOCATOR_RE = re.compile(r"(?:[.\u00b7\uff0e\u3002\u2026]{2,}|/{1,2})\s*\d{1,4}\s*$")
PRINTED_TOC_BARE_PAGE_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]|"
    r"\d{1,3}[.、]\s*|"
    r"[一二三四五六七八九十]+[、.．]\s*"
    r").{2,90}\s+\d{1,4}$"
)


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = LIST_ARTIFACT_PREFIX_RE.sub(r"\1", text)
    text = ARTIFACT_PREFIX_RE.sub("", text)
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def plain_from_spans(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return norm_text(value)
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "title_content",
            "paragraph_content",
            "list_item_content",
            "math_content",
            "code_content",
            "algorithm_content",
        ):
            if key in value:
                text = plain_from_spans(value[key])
                if text:
                    return text
        if "content" in value and isinstance(value["content"], str):
            return norm_text(value["content"])
        return " ".join(
            filter(
                None,
                (
                    plain_from_spans(v)
                    for k, v in value.items()
                    if k not in STRUCTURAL_KEYS and not k.endswith("_bbox")
                ),
            )
        )
    if isinstance(value, list):
        return "".join(plain_from_spans(item) for item in value).strip()
    return norm_text(value)


def flatten_pages(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list) and data and all(isinstance(page, list) for page in data):
        return [item for page in data for item in page if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise ValueError("Expected MinerU content_list JSON to be a list")


def rel_image(path: str, source_dir: Path, output_dir: Path) -> str:
    if not path:
        return ""
    raw = Path(path)
    if raw.is_absolute():
        target = raw
    else:
        target = source_dir / raw
    try:
        return Path(os.path.relpath(target.resolve(), output_dir.resolve())).as_posix()
    except ValueError:  # Different Windows drives require an absolute resource path.
        return target.resolve().as_posix()


def is_image_file_path(path: str, source_dir: Path) -> bool:
    if not path:
        return False
    raw = Path(path)
    target = raw if raw.is_absolute() else source_dir / raw
    if target.suffix.lower() not in IMAGE_EXTENSIONS:
        return False
    if target.exists() and not target.is_file():
        return False
    return True


def emit_caption(lines: list[str], caption: Any) -> None:
    text = plain_from_spans(caption)
    if text:
        lines.append(f"*{text}*")


def markdown_alt(text: str) -> str:
    text = re.sub(r"[\[\]\(\)\n\r]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "image"


def clean_list_item_text(text: str) -> str:
    return LIST_ITEM_ARTIFACT_RE.sub("", norm_text(text)).strip()


def image_source_path(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    source = value.get("image_source")
    if isinstance(source, dict) and source.get("path"):
        return str(source["path"])
    return ""


def clean_title_text(text: str) -> str:
    text = norm_text(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+[·.。．]?\s*\d{1,4}\s*$", "", text)
    return text.strip()


def looks_like_printed_toc_entry(text: str) -> bool:
    text = norm_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > 120:
        return False
    return bool(PRINTED_TOC_LOCATOR_RE.search(text) or PRINTED_TOC_BARE_PAGE_RE.search(text))


def heading_level(text: str, raw_level: int) -> int:
    if looks_like_printed_toc_entry(text):
        return 0
    text = clean_title_text(text)
    if not text:
        return 0
    if len(text) > 80:
        return 0
    if re.fullmatch(r"(目录|序|前言|引言|致谢|跋|后记|参考文献|附录|作者介绍|译者序|推荐序)", text):
        return 1
    if re.match(r"^第[一二三四五六七八九十百零〇\d]+[篇部卷章]\b", text):
        return 1
    if re.match(r"^第[一二三四五六七八九十百零〇\d]+节\b", text):
        return 2
    if re.match(r"^\d+\s+\S", text):
        return 2
    if re.match(r"^\d+(\.\d+){1,3}\s*\S", text):
        return min(2 + text.count("."), 4)
    if re.match(r"^[一二三四五六七八九十]+[、.．]\s*\S", text):
        return 2
    return 0


def emit_visual(
    lines: list[str],
    item: dict[str, Any],
    source_dir: Path,
    output_dir: Path,
    kind: str,
) -> None:
    content = item.get("content", {})
    if not isinstance(content, dict):
        content = {}
    image_path = (
        item.get("img_path")
        or item.get("image_path")
        or content.get("img_path")
        or content.get("image_path")
        or content.get(f"{kind}_path")
        or image_source_path(content)
    )
    table_body = item.get("table_body") or content.get("table_body") or content.get("html")
    caption = (
        item.get(f"{kind}_caption")
        or content.get(f"{kind}_caption")
        or content.get("caption")
    )
    footnote = (
        item.get(f"{kind}_footnote")
        or content.get(f"{kind}_footnote")
        or content.get("footnote")
    )

    emitted_image = False
    if image_path and is_image_file_path(str(image_path), source_dir):
        image = rel_image(str(image_path), source_dir, output_dir)
        alt = markdown_alt(plain_from_spans(caption) or kind)
        lines.append(f"![{alt}]({image})")
        emitted_image = True
    if table_body and not emitted_image:
        lines.append(str(table_body).strip())

    emit_caption(lines, caption)
    footnote_text = plain_from_spans(footnote)
    if footnote_text:
        lines.append(f"> {footnote_text}")


def block_to_markdown(
    item: dict[str, Any],
    source_dir: Path,
    output_dir: Path,
    drop_footnotes: bool,
) -> list[str]:
    item_type = item.get("type", "")
    if item_type in SKIP_TYPES:
        return []
    if item_type in {"page_footnote", "page-footnote"} and drop_footnotes:
        return []

    lines: list[str] = []

    if item_type == "text":
        text = norm_text(item.get("text") or item.get("content"))
        if not text:
            return []
        level = int(item.get("text_level") or 0)
        if level > 0:
            inferred_level = heading_level(text, level)
            text = clean_title_text(text)
            if inferred_level > 0:
                lines.append(f"{'#' * inferred_level} {text}")
            else:
                lines.append(text)
        else:
            lines.append(text)

    elif item_type in {"title"}:
        content = item.get("content", {})
        if not isinstance(content, dict):
            content = {}
        text = plain_from_spans(content.get("title_content") or item.get("content"))
        if text:
            level = int(content.get("level") or item.get("level") or 1)
            inferred_level = heading_level(text, level)
            text = clean_title_text(text)
            if inferred_level > 0:
                lines.append(f"{'#' * inferred_level} {text}")
            else:
                lines.append(f"**{text}**")

    elif item_type in {"paragraph"}:
        content = item.get("content", {})
        if not isinstance(content, dict):
            content = {}
        text = plain_from_spans(content.get("paragraph_content") or item.get("content"))
        if text:
            lines.append(text)

    elif item_type in {"image", "chart", "table"}:
        emit_visual(lines, item, source_dir, output_dir, item_type)

    elif item_type in {"equation", "equation_interline"}:
        content = item.get("content", {})
        if not isinstance(content, dict):
            content = {}
        text = (
            item.get("text")
            or content.get("math_content")
            or item.get("content")
        )
        text = plain_from_spans(text)
        image_path = item.get("img_path") or content.get("img_path") or image_source_path(content)
        if image_path:
            image = rel_image(str(image_path), source_dir, output_dir)
            lines.append(f"![{markdown_alt(text or 'equation')}]({image})")
        elif text:
            lines.append(text)

    elif item_type in {"list", "index"}:
        content = item.get("content", {})
        items = content.get("list_items") or item.get("list_items") or item.get("blocks")
        if isinstance(items, list):
            for entry in items:
                text = clean_list_item_text(plain_from_spans(entry))
                if text:
                    lines.append(f"- {text}")
        else:
            text = plain_from_spans(item.get("content") or item)
            if text:
                lines.append(text)

    elif item_type in {"code", "algorithm"}:
        content = item.get("content", {})
        code = (
            content.get("code_content")
            or content.get("algorithm_content")
            or item.get("code_body")
            or item.get("content")
        )
        code_text = plain_from_spans(code)
        caption = plain_from_spans(
            content.get("code_caption") or content.get("algorithm_caption") or item.get("code_caption")
        )
        language = content.get("code_language") or ""
        if caption:
            lines.append(f"*{caption}*")
        if code_text:
            lines.append(f"```{language}\n{code_text}\n```")

    elif item_type == "page_footnote":
        content = item.get("content", {})
        text = plain_from_spans(content.get("page_footnote_content") or item.get("content"))
        if text:
            lines.append(f"> {text}")

    else:
        text = plain_from_spans(item.get("text") or item.get("content"))
        if text:
            lines.append(text)

    return [line for line in lines if line.strip()]


def markdown_fallback(text: str) -> str:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if re.fullmatch(r"\s*\d+\s*", line):
            continue
        if re.fullmatch(r"\s*(Page|PAGE|第)\s*\d+\s*(页)?\s*", line):
            continue
        lines.append(line)
    output = "\n".join(lines)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.strip() + "\n"


def content_list_to_markdown(
    source: Path,
    output: Path,
    title: str,
    author: str,
    drop_footnotes: bool,
) -> str:
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    items = flatten_pages(data)
    blocks: list[str] = []

    if title:
        blocks.append(f"% {title}")
    if author:
        blocks.append(f"% {author}")

    for item in items:
        lines = block_to_markdown(item, source.parent, output.parent, drop_footnotes)
        if lines:
            blocks.append("\n\n".join(lines))

    text = "\n\n".join(blocks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--drop-footnotes", action="store_true")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    suffix = args.source.suffix.lower()

    if suffix == ".json":
        output = content_list_to_markdown(
            args.source,
            args.output,
            args.title,
            args.author,
            args.drop_footnotes,
        )
    else:
        original = args.source.read_text(encoding="utf-8", errors="replace")
        preface = ""
        if args.title:
            preface += f"% {args.title}\n"
        if args.author:
            preface += f"% {args.author}\n"
        output = preface + markdown_fallback(original)

    args.output.write_text(output, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
