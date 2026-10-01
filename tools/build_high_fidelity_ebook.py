#!/usr/bin/env python
"""Build a high-fidelity ebook Markdown file from MinerU V2 JSON chunks.

This converter favors visual correctness for math and tables:
- body text remains selectable/searchable Markdown text;
- display equations use MinerU's original cropped equation images with LaTeX
  preserved as alt text;
- tables include both the recognized HTML and the original table crop;
- charts/images are preserved as images.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable


SKIP_BLOCK_TYPES = {
    "page_header",
    "page_footer",
    "page_number",
    "page_aside_text",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def iter_blocks(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, dict):
        if "type" in data:
            yield data
        return
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "type" in item:
                yield item
            elif isinstance(item, list):
                yield from iter_blocks(item)


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def plain_spans(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return norm_text(value)
    if isinstance(value, list):
        return "".join(plain_spans(item) for item in value).strip()
    if isinstance(value, dict):
        item_type = value.get("type")
        content = value.get("content")
        if item_type == "equation_inline":
            latex = norm_text(content)
            return inline_math_html(latex) if latex else ""
        if item_type in {"text", "text_span"}:
            return norm_text(content)
        if "item_content" in value:
            return plain_spans(value.get("item_content"))
        if "content" in value:
            return plain_spans(content)
        return " ".join(filter(None, (plain_spans(v) for v in value.values())))
    return norm_text(value)


GREEK_AND_SYMBOLS = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\theta": "θ",
    r"\vartheta": "ϑ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\tau": "τ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Xi": "Ξ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Phi": "Φ",
    r"\Psi": "Ψ",
    r"\Omega": "Ω",
    r"\cdots": "⋯",
    r"\ldots": "…",
    r"\dots": "…",
    r"\infty": "∞",
    r"\rightarrow": "→",
    r"\Rightarrow": "⇒",
    r"\leftarrow": "←",
    r"\Leftarrow": "⇐",
    r"\leftrightarrow": "↔",
    r"\Leftrightarrow": "⇔",
    r"\pm": "±",
    r"\mp": "∓",
    r"\times": "×",
    r"\cdot": "·",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\neq": "≠",
    r"\equiv": "≡",
    r"\approx": "≈",
    r"\propto": "∝",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\int": "∫",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\in": "∈",
    r"\notin": "∉",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\circ": "°",
    r"\overline": "¯",
    r"\bar": "¯",
    r"\hat": "^",
    r"\quad": " ",
    r"\;": " ",
    r"\,": " ",
    r"\{": "{",
    r"\}": "}",
}


def replace_group_script(text: str, marker: str, tag: str) -> str:
    pattern = re.compile(rf"{re.escape(marker)}\{{([^{{}}]+)\}}")
    while True:
        new = pattern.sub(lambda m: f"<{tag}>{inline_math_inner(m.group(1))}</{tag}>", text)
        if new == text:
            return new
        text = new


def replace_simple_script(text: str, marker: str, tag: str) -> str:
    return re.sub(
        rf"{re.escape(marker)}([A-Za-z0-9+\-=∞α-ωΑ-Ω①②③④⑤⑥⑦⑧⑨])",
        lambda m: f"<{tag}>{html.escape(m.group(1))}</{tag}>",
        text,
    )


def inline_math_inner(latex: str) -> str:
    text = norm_text(latex)
    text = re.sub(
        r"\\?(?:mathrm|mathbf|mathit|mathsf|operatorname|text)\s*\{([^{}]*)\}",
        lambda m: m.group(1),
        text,
    )
    text = re.sub(r"\\?mathcal\s*\{([^{}]*)\}", lambda m: m.group(1), text)
    text = text.replace(r"\left", "").replace(r"\right", "")
    text = re.sub(
        r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
        lambda m: (
            '<span class="frac"><sup>'
            + inline_math_inner(m.group(1))
            + "</sup>/<sub>"
            + inline_math_inner(m.group(2))
            + "</sub></span>"
        ),
        text,
    )
    for command, symbol in sorted(GREEK_AND_SYMBOLS.items(), key=lambda item: -len(item[0])):
        text = text.replace(command, symbol)
    text = text.replace("^°", "°")
    text = html.escape(text)
    text = replace_group_script(text, "^", "sup")
    text = replace_group_script(text, "_", "sub")
    text = replace_simple_script(text, "^", "sup")
    text = replace_simple_script(text, "_", "sub")
    text = re.sub(r"\\?(?:mathrm|mathbf|mathit|mathsf|operatorname|text)\{([^{}]*)\}", r"\1", text)
    text = text.replace("<sup>°</sup>", "°")
    text = text.replace("\\", "")
    return text


def inline_math_html(latex: str) -> str:
    body = inline_math_inner(latex)
    return f'<span class="math-inline">{body}</span>'


def copy_asset(path: str, source_dir: Path, asset_dir: Path, prefix: str) -> str:
    source = source_dir / path
    if not source.exists():
        return ""
    target = asset_dir / f"{prefix}-{source.name}"
    if not target.exists():
        shutil.copy2(source, target)
    return target.name


def image_markdown(filename: str, alt: str, css_class: str = "") -> str:
    alt = re.sub(r"[\]\n\r]+", " ", alt).strip() or "image"
    if css_class:
        return f'<div class="{css_class}"><img src="assets/{filename}" alt="{html.escape(alt)}" /></div>'
    return f"![{alt}](assets/{filename})"


def caption_text(caption: Any) -> str:
    text = plain_spans(caption)
    return text.strip()


def emit_paragraph(block: dict[str, Any]) -> list[str]:
    content = block.get("content") or {}
    text = plain_spans(content.get("paragraph_content") or content)
    return [text] if text else []


def emit_title(block: dict[str, Any]) -> list[str]:
    content = block.get("content") or {}
    text = plain_spans(content.get("title_content") or content)
    if not text:
        return []
    level = int(content.get("level") or block.get("level") or 1)
    level = max(1, min(level, 6))
    return [f"{'#' * level} {text}"]


def emit_list(block: dict[str, Any]) -> list[str]:
    content = block.get("content") or {}
    items = content.get("list_items") or []
    lines: list[str] = []
    for item in items:
        text = plain_spans(item.get("item_content") if isinstance(item, dict) else item)
        if text:
            lines.append(f"- {text}")
    return ["\n".join(lines)] if lines else []


def emit_footnote(block: dict[str, Any]) -> list[str]:
    content = block.get("content") or {}
    text = plain_spans(content.get("page_footnote_content") or content)
    return [f"> {text}"] if text else []


def emit_equation(
    block: dict[str, Any],
    source_dir: Path,
    asset_dir: Path,
    prefix: str,
) -> list[str]:
    content = block.get("content") or {}
    latex = norm_text(content.get("math_content"))
    image = content.get("image_source") or {}
    rel = ""
    if isinstance(image, dict) and image.get("path"):
        rel = copy_asset(str(image["path"]), source_dir, asset_dir, prefix)
    lines: list[str] = []
    if rel:
        lines.append(image_markdown(rel, latex or "equation", "display-equation"))
    elif latex:
        lines.append(f"$$\n{latex}\n$$")
    if latex:
        lines.append(f'<div class="latex-source">{html.escape(latex)}</div>')
    return lines


def emit_table(
    block: dict[str, Any],
    source_dir: Path,
    asset_dir: Path,
    prefix: str,
) -> list[str]:
    content = block.get("content") or {}
    caption = caption_text(content.get("table_caption"))
    footnote = caption_text(content.get("table_footnote"))
    html_table = math_in_html(norm_text(content.get("html")))
    image = content.get("image_source") or {}
    rel = ""
    if isinstance(image, dict) and image.get("path"):
        rel = copy_asset(str(image["path"]), source_dir, asset_dir, prefix)

    lines: list[str] = []
    if caption:
        lines.append(f"*{caption}*")
    if rel:
        lines.append(image_markdown(rel, caption or "table", "table-image"))
    if html_table:
        lines.append(f'<div class="recognized-table">\n{html_table}\n</div>')
    if footnote:
        lines.append(f"> {footnote}")
    return lines


def math_in_html(value: str) -> str:
    if not value:
        return ""
    return re.sub(
        r"\$([^$\n]+)\$",
        lambda match: inline_math_html(html.unescape(match.group(1))),
        value,
    )


def emit_visual(
    block: dict[str, Any],
    source_dir: Path,
    asset_dir: Path,
    prefix: str,
) -> list[str]:
    content = block.get("content") or {}
    image = content.get("image_source") or {}
    rel = ""
    if isinstance(image, dict) and image.get("path"):
        rel = copy_asset(str(image["path"]), source_dir, asset_dir, prefix)
    text = norm_text(content.get("content"))
    cap = caption_text(content.get("image_caption") or content.get("chart_caption"))
    footnote = caption_text(content.get("image_footnote") or content.get("chart_footnote"))
    alt = cap or text or block.get("type") or "image"
    lines: list[str] = []
    if cap:
        lines.append(f"*{cap}*")
    if rel:
        lines.append(image_markdown(rel, alt, "figure-image"))
    if text and block.get("type") == "chart":
        lines.append(text)
    if footnote:
        lines.append(f"> {footnote}")
    return lines


def emit_block(
    block: dict[str, Any],
    source_dir: Path,
    asset_dir: Path,
    prefix: str,
) -> list[str]:
    block_type = block.get("type")
    if block_type in SKIP_BLOCK_TYPES:
        return []
    if block_type == "title":
        return emit_title(block)
    if block_type == "paragraph":
        return emit_paragraph(block)
    if block_type == "list":
        return emit_list(block)
    if block_type == "page_footnote":
        return emit_footnote(block)
    if block_type == "equation_interline":
        return emit_equation(block, source_dir, asset_dir, prefix)
    if block_type == "table":
        return emit_table(block, source_dir, asset_dir, prefix)
    if block_type in {"image", "chart"}:
        return emit_visual(block, source_dir, asset_dir, prefix)
    text = plain_spans(block.get("content") or block)
    return [text] if text else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default="")
    args = parser.parse_args()

    json_files = sorted(args.input_root.glob("mineru-part-*/source/vlm/source_content_list_v2.json"))
    if not json_files:
        raise SystemExit(f"No MinerU V2 JSON files found under {args.input_root}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    asset_dir = args.output.parent / "assets"
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True)

    blocks_out: list[str] = []
    if args.title:
        blocks_out.append(f"# {args.title}")
    if args.author:
        blocks_out.append(args.author)

    for index, path in enumerate(json_files):
        source_dir = path.parent
        prefix = f"p{index:03d}"
        for block in iter_blocks(read_json(path)):
            emitted = emit_block(block, source_dir, asset_dir, prefix)
            for item in emitted:
                if item.strip():
                    blocks_out.append(item.strip())

    text = "\n\n".join(blocks_out)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    args.output.write_text(text.strip() + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Assets: {len(list(asset_dir.iterdir()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
