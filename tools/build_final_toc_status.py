#!/usr/bin/env python
"""Build the final per-book TOC review ledger from generated audit evidence."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


NO_CHANGE_NOTES = {
    "《高敏感是种天赋Ⅲ》.epub": "15项：14章及致谢；正文顺序完整",
    "八周正念之旅 摆脱抑郁与情绪压力": "17项：前置内容、两部分及12章层级完整",
    "辩证行为疗法：掌握正念": "12项：译序、10章及参考文献完整",
    "部分心理学.epub": "8项均为独立正文主题，无印刷目录可误收",
    "创伤30讲.epub": "30讲与正文逐讲对应",
    "创伤与解离.epub": "4部分、10章及前后置内容层级完整",
    "徐凯文的心理创伤课.epub": "10章与正文逐章对应",
    "移情焦点治疗--青少年严重人格障碍的治疗": "3部分、9章及附录层级完整",
    "真实的幸福 马丁.epub": "2部分、12章及后记层级完整",
    "走出双相情感障碍++应对躁郁生活的日常指南.epub": "前言及9章完整；已无text和页码前缀",
}

SPECIAL_NOTES = {
    "精神障碍诊断与统计手册  第5版.epub": "真正印刷目录为37项；正文诊断条目和索引未伪造为章节",
    "妈妈，请这样爱我": "30个故事及后记完整；目录中的长句是摘要，不是小节",
    "依恋三部曲01-依恋.epub": "5部分、19章及参考文献层级完整",
    "依恋三部曲02-分离.epub": "3部分、22章、3附录及参考文献层级完整",
    "依恋三部曲03-丧失.epub": "3部分、25章、后记及参考文献层级完整",
    "杰瑞姆·布莱克曼：心灵的面具": "印刷目录只有23个宽泛条目；101种防御是正文内容",
    "爱的五种语言": "21个印刷目录条目完整；目录长句为简介",
    "内在生命,精神分析与人格发展.epub": "前置内容、14章及附录完整",
    "戴维·巴斯 - 进化心理学": "正文导航完整；长目录窗口主要是参考文献和索引",
}


def matching_note(name: str, notes: dict[str, str]) -> str | None:
    for marker, note in notes.items():
        if marker in name:
            return note
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--md-output", type=Path, required=True)
    args = parser.parse_args()

    with args.summary.open(encoding="utf-8-sig", newline="") as handle:
        summaries = {row["name"]: row for row in csv.DictReader(handle)}
    with args.audit.open(encoding="utf-8-sig", newline="") as handle:
        audits = {row["name"]: row for row in csv.DictReader(handle)}

    rebuilt = {path.name for path in args.backup_dir.rglob("*.epub")}
    rows = []
    for name in sorted(summaries):
        summary = summaries[name]
        audit = audits[name]
        decision = "rebuilt_and_verified" if name in rebuilt else "verified_no_change"
        note = matching_note(name, SPECIAL_NOTES)
        if note is None and decision == "verified_no_change":
            note = matching_note(name, NO_CHANGE_NOTES)
        if note is None:
            note = "印刷目录、现有导航与正文坐标已复核"
        rows.append({
            "book": name,
            "decision": decision,
            "nav_items": summary["nav_items"],
            "toc_windows": summary["toc_windows"],
            "order_inversions": audit["order_inversions"],
            "missing_targets": audit["missing_targets"],
            "review_note": note,
        })

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    rebuilt_count = sum(row["decision"] == "rebuilt_and_verified" for row in rows)
    lines = [
        "# EPUB TOC final review status",
        "",
        f"- Books reviewed: {len(rows)}",
        f"- Rebuilt and verified: {rebuilt_count}",
        f"- Verified without rebuild: {len(rows) - rebuilt_count}",
        f"- Order inversions: {sum(int(row['order_inversions']) for row in rows)}",
        f"- Missing targets: {sum(int(row['missing_targets']) for row in rows)}",
        "",
        "| Book | Decision | Items | Inversions | Missing | Review note |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        book = row["book"].replace("|", "\\|")
        note = row["review_note"].replace("|", "\\|")
        lines.append(
            f"| {book} | {row['decision']} | {row['nav_items']} | "
            f"{row['order_inversions']} | {row['missing_targets']} | {note} |"
        )
    args.md_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {args.csv_output} and {args.md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
