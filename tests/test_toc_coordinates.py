from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from apply_epub_toc_coordinates import BLOCK_TAGS, clean, find_book, insert_anchors


def content_nodes(raw: bytes):
    soup = BeautifulSoup(raw, "lxml")
    return [
        node
        for node in soup.find_all(list(BLOCK_TAGS))
        if clean(node.get_text(" ", strip=True))
    ]


class TocCoordinateTests(unittest.TestCase):
    def test_anchor_uses_parser_block_coordinates_for_malformed_html(self) -> None:
        raw = b"<html><body><p>zero<p><strong>one</strong></p><p>two</p></body></html>"
        expected = clean(content_nodes(raw)[1].get_text(" ", strip=True))

        updated = insert_anchors(raw, [(1, "manual_toc_1")], remove_existing=True)
        soup = BeautifulSoup(updated, "lxml")
        anchor = soup.find(id="manual_toc_1")

        self.assertIsNotNone(anchor)
        self.assertEqual(expected, clean(anchor.find_parent(list(BLOCK_TAGS)).get_text(" ", strip=True)))

    def test_shared_block_anchor_order_is_stable(self) -> None:
        updated = insert_anchors(
            b"<html><body><p>chapter</p></body></html>",
            [(0, "manual_toc_1"), (0, "manual_toc_2")],
            remove_existing=True,
        )
        soup = BeautifulSoup(updated, "lxml")

        self.assertEqual(
            ["manual_toc_1", "manual_toc_2"],
            [node.get("id") for node in soup.p.find_all("a", recursive=False)],
        )

    def test_exact_filename_with_brackets_is_not_treated_as_glob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "[reviewed].epub"
            expected.touch()
            self.assertEqual(expected, find_book(Path(directory), expected.name))


if __name__ == "__main__":
    unittest.main()
