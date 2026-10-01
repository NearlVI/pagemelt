#!/usr/bin/env python
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


IMAGE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)$")
HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.+)$")
ARTIFACT_PREFIX_RE = re.compile(
    r"(?i)^\s*(?:text|paragraph)\s*(?:[-:：]\s*|\s+(?=(?:\d{1,4}\b|[\u4e00-\u9fff])))"
)
LIST_ARTIFACT_PREFIX_RE = re.compile(
    r"(?i)^(\s*[-*+]\s+)(?:text|paragraph)\b(?:\s*[-:：·●◎◆■]\s*|\s+)"
)
RAW_HTML_RE = re.compile(
    r"^</?(table|thead|tbody|tfoot|tr|td|th|colgroup|col|caption|div|span|p|br)\b",
    re.IGNORECASE,
)
FALLBACK_HEADING_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇\d]+[讲章节篇部]\b.*|"
    r"第[一二三四五六七八九十]+部分\b.*"
    r")$"
)
PRINTED_TOC_LOCATOR_RE = re.compile(r"(?:[.\u00b7\uff0e\u3002\u2026]{2,}|/{1,2})\s*\d{1,4}\s*$")
PRINTED_TOC_BARE_PAGE_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇\d]+[篇部卷章节讲]|"
    r"\d{1,3}[.、]\s*|"
    r"[一二三四五六七八九十]+[、.．]\s*"
    r").{2,90}\s+\d{1,4}$"
)
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


def flush_paragraph(lines: list[str], out: list[str]) -> None:
    if not lines:
        return
    text = " ".join(line.strip() for line in lines if line.strip())
    if text:
        text = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", html.escape(text))
        out.append(f"<p>{text}</p>")
    lines.clear()


def clean_artifact_prefix(text: str) -> str:
    text = LIST_ARTIFACT_PREFIX_RE.sub(r"\1", text)
    return ARTIFACT_PREFIX_RE.sub("", text).strip()


def looks_like_printed_toc_entry(text: str) -> bool:
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > 120:
        return False
    return bool(PRINTED_TOC_LOCATOR_RE.search(text) or PRINTED_TOC_BARE_PAGE_RE.search(text))


def looks_like_fallback_heading(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 90:
        return False
    if looks_like_printed_toc_entry(text):
        return False
    if text.endswith(("。", "；", "，", "！", "？", "：", ";", ",", ".", "!", "?")):
        return False
    return FALLBACK_HEADING_RE.match(text) is not None


def convert(source: Path, title: str) -> str:
    source_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    heading_levels: list[int] = []
    for raw in source_lines:
        stripped = raw.strip()
        heading = HEADING_RE.match(stripped)
        if not heading:
            continue
        text = heading.group("text").strip()
        if text == "目录":
            continue
        heading_levels.append(len(heading.group("marks")))
    min_heading_level = min(heading_levels) if heading_levels else 0
    use_fallback_headings = min_heading_level == 0

    out = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(title or source.stem)}</title>",
        "<style>",
        "body{font-family:serif;line-height:1.55;}",
        "img{max-width:100%;height:auto;display:block;margin:1em auto;}",
        "table{border-collapse:collapse;width:100%;font-size:0.9em;}",
        "td,th{border:1px solid #999;padding:0.2em 0.35em;}",
        "blockquote{border-left:3px solid #bbb;margin-left:0;padding-left:1em;color:#555;}",
        "</style>",
        "</head>",
        "<body>",
    ]
    paragraph: list[str] = []
    in_list = False
    in_pre = False
    pre_lines: list[str] = []

    for raw in source_lines:
        line = raw.rstrip()
        stripped = clean_artifact_prefix(line.strip())

        if stripped.startswith("% "):
            continue

        if stripped.startswith("```"):
            flush_paragraph(paragraph, out)
            if in_pre:
                out.append("<pre><code>" + html.escape("\n".join(pre_lines)) + "</code></pre>")
                pre_lines = []
                in_pre = False
            else:
                in_pre = True
            continue
        if in_pre:
            pre_lines.append(line)
            continue

        if not stripped:
            flush_paragraph(paragraph, out)
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        if RAW_HTML_RE.match(stripped):
            flush_paragraph(paragraph, out)
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(stripped)
            continue

        heading = HEADING_RE.match(stripped)
        if heading:
            flush_paragraph(paragraph, out)
            if in_list:
                out.append("</ul>")
                in_list = False
            text = heading.group("text").strip()
            if text == "目录":
                out.append(f"<p><strong>{html.escape(text)}</strong></p>")
                continue
            if looks_like_printed_toc_entry(text):
                out.append(f"<p><strong>{html.escape(text)}</strong></p>")
                continue
            level = len(heading.group("marks"))
            if min_heading_level:
                level = max(1, min(3, level - min_heading_level + 1))
            out.append(f"<h{level}>{html.escape(text)}</h{level}>")
            continue

        image = IMAGE_RE.match(stripped)
        if image:
            flush_paragraph(paragraph, out)
            if in_list:
                out.append("</ul>")
                in_list = False
            src_text = image.group("src").strip()
            if Path(src_text).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            alt = html.escape(image.group("alt"))
            src = html.escape(src_text, quote=True)
            out.append(f'<figure><img src="{src}" alt="{alt}"></figure>')
            continue

        if stripped.startswith("- "):
            flush_paragraph(paragraph, out)
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(stripped[2:].strip())}</li>")
            continue

        if stripped.startswith("> "):
            flush_paragraph(paragraph, out)
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote>{html.escape(stripped[2:].strip())}</blockquote>")
            continue

        if use_fallback_headings and looks_like_fallback_heading(stripped):
            flush_paragraph(paragraph, out)
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{html.escape(stripped)}</h1>")
            continue

        paragraph.append(stripped)

    flush_paragraph(paragraph, out)
    if in_list:
        out.append("</ul>")
    if in_pre:
        out.append("<pre><code>" + html.escape("\n".join(pre_lines)) + "</code></pre>")
    out.extend(["</body>", "</html>"])
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args()
    args.output.write_text(convert(args.source, args.title), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
