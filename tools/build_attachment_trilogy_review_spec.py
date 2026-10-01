#!/usr/bin/env python
"""Build manually reviewed TOCs for Bowlby's attachment trilogy."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from build_toc_review_packets import extract_blocks, spine


BOOKS = [
    {
        "file": "依恋三部曲01-依恋.epub",
        "parts": [
            ("第一部分 任务", "ebook_source_split_003.html", 26, 1, 2),
            ("第二部分 本能行为", "ebook_source_split_005.html", 53, 3, 10),
            ("第三部分 依恋行为", "ebook_source_split_015.html", 154, 11, 13),
            ("第四部分 人类依恋的个体发生", "ebook_source_split_019.html", 163, 14, 17),
            ("第五部分 旧议题和新发现", "ebook_source_split_024.html", 48, 18, 19),
        ],
        "chapters": [
            ("第一章 观点", "ebook_source_split_004.html"),
            ("第二章 尚待解释的观察所得", "ebook_source_split_005.html"),
            ("第三章 本能行为：一个替代模型", "ebook_source_split_006.html"),
            ("第四章 人类对环境的进化适应性", "ebook_source_split_008.html"),
            ("第五章 调节本能行为的行为系统", "ebook_source_split_009.html"),
            ("第六章 本能行为的归因", "ebook_source_split_010.html"),
            ("第七章 评估与选择：感受与情绪", "ebook_source_split_011.html"),
            ("第八章 本能行为的功能", "ebook_source_split_013.html"),
            ("第九章 生命周期中行为的改变", "ebook_source_split_014.html"),
            ("第十章 本能行为的发育", "ebook_source_split_015.html"),
            ("第十一章 儿童与母亲的联结：依恋行为", "ebook_source_split_016.html"),
            ("第十二章 依恋行为的本质与功能", "ebook_source_split_017.html"),
            ("第十三章 依恋行为的控制系统观点", "ebook_source_split_018.html"),
            ("第十四章 依恋行为的开始", "ebook_source_split_020.html"),
            ("第十五章 聚焦在一个对象上", "ebook_source_split_021.html"),
            ("第十六章 依恋的模式和影响因素", "ebook_source_split_023.html"),
            ("第十七章 依恋行为组织的发展", "ebook_source_split_024.html"),
            ("第十八章 依恋模式的稳定和变化", "ebook_source_split_025.html"),
            ("第十九章 反对、误解和澄清", "ebook_source_split_026.html"),
        ],
        "after": [("参考文献", "ebook_source_split_027.html", 0)],
    },
    {
        "file": "依恋三部曲02-分离.epub",
        "parts": [
            ("第一部分 安全焦虑与困扰", "ebook_source_split_003.html", 30, 1, 4),
            ("第二部分 研究人类恐惧的行为学方法", "ebook_source_split_007.html", 105, 5, 12),
            ("第三部分 对恐惧的敏感性的个体差异：焦虑型依恋", "ebook_source_split_015.html", 37, 13, 22),
        ],
        "chapters": [
            ("第一章 人类悲伤的原型", "ebook_source_split_004.html"),
            ("第二章 分离与丧失在精神病理学中的地位", "ebook_source_split_005.html"),
            ("第三章 母亲在场或者母亲不在场时的行为表现：人类", "ebook_source_split_006.html"),
            ("第四章 母亲在场或者母亲不在场时的行为表现：非人类灵长类动物", "ebook_source_split_007.html"),
            ("第五章 焦虑与恐惧理论的基本假设", "ebook_source_split_008.html"),
            ("第六章 预示恐惧的行为", "ebook_source_split_009.html"),
            ("第七章 唤起人类恐惧感的情境", "ebook_source_split_010.html"),
            ("第八章 可引起动物恐惧的情境", "ebook_source_split_011.html"),
            ("第九章 危险和安全的自然线索", "ebook_source_split_012.html"),
            ("第十章 自然线索、文化线索，以及对危险的评估", "ebook_source_split_013.html"),
            ("第十一章 合理化、错误归因和投射", "ebook_source_split_014.html"),
            ("第十二章 对分离的恐惧", "ebook_source_split_015.html"),
            ("第十三章 一些导致个体差异的变量", "ebook_source_split_016.html"),
            ("第十四章 对于恐惧的敏感性以及依恋对象的可得性", "ebook_source_split_017.html"),
            ("第十五章 焦虑型依恋及一些促成条件", "ebook_source_split_018.html"),
            ("第十六章 “过度依赖”和溺爱理论", "ebook_source_split_019.html"),
            ("第十七章 愤怒、焦虑和依恋", "ebook_source_split_020.html"),
            ("第十八章 焦虑型依恋和儿童时期的“恐怖症”", "ebook_source_split_021.html"),
            ("第十九章 焦虑型依恋和“广场恐怖症”", "ebook_source_split_022.html"),
            ("第二十章 家庭背景的遗漏、压抑和弄虚作假", "ebook_source_split_023.html"),
            ("第二十一章 安全依恋与自立的成长", "ebook_source_split_024.html"),
            ("第二十二章 人格成长的路径", "ebook_source_split_025.html"),
        ],
        "after": [
            ("附录1 分离焦虑：文献综述", "ebook_source_split_025.html", 38),
            ("附录2 精神分析和进化论", "ebook_source_split_025.html", 134),
            ("附录3 专业术语的问题", "ebook_source_split_025.html", 148),
            ("参考文献", "ebook_source_split_026.html", 0),
        ],
    },
    {
        "file": "依恋三部曲03-丧失.epub",
        "parts": [
            ("第一部分 观察，概念，争论", "ebook_source_split_003.html", 31, 1, 5),
            ("第二部分 成人的哀悼", "ebook_source_split_008.html", 7, 6, 14),
            ("第三部分 儿童的哀悼", "ebook_source_split_018.html", 93, 15, 25),
        ],
        "chapters": [
            ("第一章 丧失的创伤", "ebook_source_split_004.html"),
            ("第二章 丧失与哀悼在病理心理学中的地位", "ebook_source_split_005.html"),
            ("第三章 概念框架", "ebook_source_split_006.html"),
            ("第四章 防御的信息加工方法", "ebook_source_split_007.html"),
            ("第五章 工作计划", "ebook_source_split_008.html"),
            ("第六章 丧失配偶", "ebook_source_split_009.html"),
            ("第七章 丧失孩子", "ebook_source_split_010.html"),
            ("第八章 其他文化中的哀悼", "ebook_source_split_012.html"),
            ("第九章 失调的变式", "ebook_source_split_013.html"),
            ("第十章 影响哀悼进程的条件", "ebook_source_split_014.html"),
            ("第十一章 倾向于哀悼失调的人的人格特点", "ebook_source_split_015.html"),
            ("第十二章 倾向于哀悼失调的人的童年经历", "ebook_source_split_016.html"),
            ("第十三章 引起丧失反应变化的认知过程", "ebook_source_split_017.html"),
            ("第十四章 悲伤、抑郁状态和抑郁障碍", "ebook_source_split_018.html"),
            ("第十五章 在儿童期和青少年期经历父母的死亡", "ebook_source_split_019.html"),
            ("第十六章 外部条件良好时儿童的反应", "ebook_source_split_020.html"),
            ("第十七章 儿童期丧失与精神病性障碍", "ebook_source_split_021.html"),
            ("第十八章 导致结果差异的条件", "ebook_source_split_022.html"),
            ("第十九章 当条件不利的情况下儿童的反应", "ebook_source_split_023.html"),
            ("第二十章 失活和被区隔系统的概念", "ebook_source_split_024.html"),
            ("第二十一章 失调的变式和对此有影响的一些情况", "ebook_source_split_025.html"),
            ("第二十二章 父亲或母亲自杀的影响", "ebook_source_split_026.html"),
            ("第二十三章 3—4岁儿童对于丧失的反应", "ebook_source_split_027.html"),
            ("第二十四章 2岁儿童对丧失的反应", "ebook_source_split_028.html"),
            ("第二十五章 根据早期认知发展所知的幼童反应", "ebook_source_split_029.html"),
        ],
        "after": [
            ("后记", "ebook_source_split_030.html", 0),
            ("参考文献", "ebook_source_split_031.html", 0),
        ],
    },
]


def make_entry(label: str, file_name: str, block_index: int, blocks) -> dict[str, object]:
    block = blocks[(file_name, block_index)]
    return {
        "label": label,
        "file": file_name,
        "block": block_index,
        "expect": block.text[:80],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    books_output = []
    for spec in BOOKS:
        path = args.epub_dir / spec["file"]
        with zipfile.ZipFile(path) as epub:
            files = spine(epub)
            all_blocks = extract_blocks(epub, files)
        blocks = {(block.file_name, block.block_index): block for block in all_blocks}

        entries = [
            make_entry("致谢", "ebook_source_split_001.html", 0, blocks),
            make_entry("前言", "ebook_source_split_002.html", 0, blocks),
        ]
        for part_label, part_file, part_block, first, last in spec["parts"]:
            part = make_entry(part_label, part_file, part_block, blocks)
            part["children"] = [
                make_entry(label, file_name, 0, blocks)
                for label, file_name in spec["chapters"][first - 1 : last]
            ]
            entries.append(part)
        entries.extend(make_entry(*item, blocks) for item in spec["after"])
        books_output.append({"file": spec["file"], "entries": entries})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"books": books_output}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} for {len(books_output)} books")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
