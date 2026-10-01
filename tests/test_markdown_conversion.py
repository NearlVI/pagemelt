import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from mineru_content_to_markdown import block_to_markdown, rel_image
from markdown_to_simple_html import flush_paragraph


class MarkdownTests(unittest.TestCase):
    def test_printed_toc_page_number_checked_before_cleaning(self):
        for item in [
            {'type': 'text', 'text': '第一章 示例标题 12', 'text_level': 1},
            {'type': 'title', 'content': {'title_content': '第一章 示例标题 12', 'level': 1}},
        ]:
            rendered = block_to_markdown(item, Path('.'), Path('.'), False)
            self.assertFalse(any(line.startswith('#') for line in rendered))

    def test_image_path_when_output_is_outside_extraction_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'mineru'
            output = root / 'build'
            relative = rel_image('images/photo.png', source, output)
            self.assertEqual((output / relative).resolve(), (source / 'images/photo.png').resolve())

    def test_bold_text_escaped_once(self):
        out = []
        flush_paragraph(['**A & B < C**'], out)
        self.assertEqual(out, ['<p><strong>A &amp; B &lt; C</strong></p>'])
