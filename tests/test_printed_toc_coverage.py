from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from measure_printed_toc_coverage import (
    account,
    key,
    measure_book,
    spec_labels,
    strip_page_suffix,
)
from resolve_toc_search_specs import resolve_book


def make_epub(path: Path, labels: list[tuple[str, str, str]]) -> None:
    """labels: (printed line, page number, body heading id text)."""
    toc_blocks = "".join(
        f"<p>{line}……{page}</p>" for line, page, _ in labels
    )
    body_blocks = "".join(f'<h1 id="s{i}">{text}</h1>' for i, (_, _, text) in enumerate(labels))
    extra = "<h1 id='afterword'>后记</h1>"
    nav = "".join(
        f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{text}</text></navLabel>'
        f'<content src="../Text/ch.xhtml#s{i}"/></navPoint>'
        for i, (_, _, text) in enumerate(labels, 1)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="toc" href="Text/toc.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="chapter" href="Text/ch.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="Nav/toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest><spine toc="ncx"><itemref idref="toc"/><itemref idref="chapter"/></spine></package>',
        )
        z.writestr(
            "OEBPS/Nav/toc.ncx",
            f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{nav}</navMap></ncx>',
        )
        z.writestr("OEBPS/Text/toc.xhtml", f"<html><body>{toc_blocks}</body></html>")
        z.writestr("OEBPS/Text/ch.xhtml", f"<html><body>{body_blocks}{extra}</body></html>")


CHAPTERS = [
    ("第一章 起点", "3", "第一章 起点"),
    ("第二章 转折", "15", "第二章 转折"),
    ("第三章 结局", "42", "第三章 结局"),
    ("附录 量表", "55", "附录 量表"),
    ("致谢", "60", "致谢"),
]


def spec_for(book: str, entries: list[dict], dropped: list[dict]) -> dict:
    return {"file": book, "entries": entries, "dropped": dropped}


def restore_entries() -> list[dict]:
    return [
        {"label": "第一章 起点", "search": "第一章 起点"},
        {"label": "第二章 转折", "search": "第二章 转折"},
        {"label": "第三章 结局", "search": "第三章 结局"},
        {
            "label": "后记",
            "search": "后记",
            "deviation": "印刷目录未收录；正文有独立标题，经确认增补",
        },
    ]


class NormalizationTests(unittest.TestCase):
    def test_key_strips_punctuation_and_pipes(self):
        self.assertEqual(key("第一章 起点"), key("第一章|起点"))
        self.assertEqual(key("A B"), key("a b"))

    def test_strip_page_suffix_variants(self):
        self.assertEqual(strip_page_suffix("第一章……12"), "第一章")
        self.assertEqual(strip_page_suffix("导言|11|"), "导言")


class AccountTests(unittest.TestCase):
    def test_full_contract_passes(self):
        labels, deviations, dropped, renamed = spec_labels(
            spec_for("b.epub", restore_entries(), [{"line": "附录 量表", "reason": "版权页"}, {"line": "致谢", "reason": "无正文对应"}])
        )
        result = account(
            [strip_page_suffix(f"{line}……{page}") for line, page, _ in CHAPTERS],
            labels,
            deviations,
            dropped,
            renamed,
        )
        self.assertEqual(result["restored"], 3)
        self.assertEqual(result["explained"], 2)
        self.assertEqual(result["silent_missing"], [])
        self.assertEqual(result["unexplained_additions"], [])

    def test_silent_missing_and_unexplained_addition(self):
        labels, deviations, dropped, renamed = spec_labels(
            spec_for("b.epub", restore_entries(), [{"line": "附录 量表", "reason": "版权页"}])
        )
        result = account(
            [strip_page_suffix(f"{line}……{page}") for line, page, _ in CHAPTERS],
            labels,
            deviations,
            dropped,
            renamed,
        )
        self.assertEqual(result["restored"], 3)
        self.assertEqual(result["explained"], 1)
        self.assertEqual(result["silent_missing"], ["致谢"])

        bare = [
            {"label": "后记", "search": "后记"},  # addition without deviation mark
        ]
        labels2, deviations2, dropped2, renamed2 = spec_labels(spec_for("b.epub", bare, []))
        result2 = account([], labels2, deviations2, dropped2, renamed2)
        self.assertEqual(result2["unexplained_additions"], [key("后记")])

    def test_renamed_label_restores_its_printed_line(self):
        # Printed line OCR-damaged; label taken from the body heading and the
        # entry declares which printed line it restores.
        entry = {
            "label": "第三章 结局",
            "search": "第三章 结局",
            "printed": "第三章 结同",
            "deviation": "印刷行 OCR 损坏（结同→结局），标签采用正文标题",
        }
        labels, deviations, dropped, renamed = spec_labels(spec_for("b.epub", [entry], []))
        result = account(["第三章 结同"], labels, deviations, dropped, renamed)
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["silent_missing"], [])
        self.assertEqual(result["unexplained_additions"], [])

    def test_rename_without_printed_declaration_stays_silent(self):
        entry = {"label": "第三章 结局", "search": "第三章 结局", "deviation": "改用正文标题"}
        labels, deviations, dropped, renamed = spec_labels(spec_for("b.epub", [entry], []))
        result = account(["第三章 结同"], labels, deviations, dropped, renamed)
        # deviation explains the label, but the printed line still has no home
        self.assertEqual(result["silent_missing"], ["第三章 结同"])
        self.assertEqual(result["unexplained_additions"], [])

    def test_wrapped_title_restored_by_pair_join(self):
        labels, _, _, _ = spec_labels(
            spec_for("b.epub", [{"label": "很长的章节标题完整还原", "search": "x"}], [])
        )
        result = account(["很长的章节", "标题完整还原"], labels)
        self.assertEqual(result["restored"], 2)
        self.assertEqual(result["silent_missing"], [])


class MeasureBookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / "book.epub"
        make_epub(self.book, CHAPTERS)

    def test_report_mode_matches_ncx(self):
        row = measure_book(self.book, None)
        self.assertEqual(row["has_printed_toc"], True)
        self.assertEqual(row["printed_lines"], 5)
        self.assertEqual(row["printed_matched"], 5)
        self.assertEqual(row["printed_coverage"], 1.0)

    def test_gate_mode_accounts_contract(self):
        spec = spec_for(
            "book.epub",
            restore_entries(),
            [{"line": "附录 量表", "reason": "版权页"}, {"line": "致谢", "reason": "无正文对应"}],
        )
        row = measure_book(self.book, spec)
        self.assertEqual(row["restored"], 3)
        self.assertEqual(row["explained_dropped"], 2)
        self.assertEqual(row["silent_missing"], 0)


class ResolvePassthroughTests(unittest.TestCase):
    def test_deviation_printed_and_dropped_survive_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp) / "book.epub"
            make_epub(book, CHAPTERS)
            spec = spec_for(
                "book.epub",
                restore_entries(),
                [{"line": "致谢", "reason": "无正文对应"}],
            )
            spec["entries"][2]["printed"] = "第三章 结同"
            spec["entries"][2]["deviation"] = "印刷行 OCR 损坏，标签采用正文标题"
            resolved = resolve_book(book, spec)
        self.assertEqual(len(resolved["entries"]), 4)
        marked = {e["label"]: e for e in resolved["entries"] if e.get("deviation")}
        self.assertEqual(set(marked), {"第三章 结局", "后记"})
        self.assertEqual(marked["第三章 结局"]["printed"], "第三章 结同")
        self.assertEqual(resolved["dropped"], [{"line": "致谢", "reason": "无正文对应"}])


class GateExitCodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_epub(self.root / "book.epub", CHAPTERS)

    def run_gate(self, spec: dict, *flags: str) -> subprocess.CompletedProcess:
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps({"books": [spec]}, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(TOOLS / "measure_printed_toc_coverage.py"),
             str(self.root), "--spec", spec_path, *flags],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    def test_pass_declared_fail_silent_fail_strict(self):
        good = spec_for(
            "book.epub", restore_entries(),
            [{"line": "附录 量表", "reason": "版权页"}, {"line": "致谢", "reason": "无正文对应"}],
        )
        self.assertEqual(self.run_gate(good).returncode, 0)

        silent = spec_for("book.epub", restore_entries(), [{"line": "附录 量表", "reason": "版权页"}])
        self.assertEqual(self.run_gate(silent).returncode, 3)

        unmarked = spec_for(
            "book.epub",
            [{"label": "第一章 起点", "search": "第一章 起点"},
             {"label": "第二章 转折", "search": "第二章 转折"},
             {"label": "第三章 结局", "search": "第三章 结局"},
             {"label": "后记", "search": "后记"}],
            [{"line": "附录 量表", "reason": "版权页"}, {"line": "致谢", "reason": "无正文对应"}],
        )
        self.assertEqual(self.run_gate(unmarked).returncode, 0)
        self.assertEqual(self.run_gate(unmarked, "--strict-additions").returncode, 4)


if __name__ == "__main__":
    unittest.main()
