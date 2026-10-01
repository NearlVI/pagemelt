from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from export_epub_toc_coordinates import export_book
from validate_epub_toc_acceptance import validate_book
from apply_epub_toc_coordinates import apply_one, validate_spec


def make_epub(path, body='<h1 id="ch">Chapter</h1><p>Body</p>', targets=None, mimetype=b'application/epub+zip'):
    targets = targets or [('Chapter', '../Text/ch.xhtml#ch')]
    nav = ''.join(f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{label}</text></navLabel><content src="{src}"/></navPoint>' for i, (label, src) in enumerate(targets, 1))
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', mimetype)
        z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>')
        z.writestr('OEBPS/book.opf', '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="chapter" href="Text/ch.xhtml" media-type="application/xhtml+xml"/><item id="ncx" href="Nav/toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine toc="ncx"><itemref idref="chapter"/></spine></package>')
        z.writestr('OEBPS/Nav/toc.ncx', f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{nav}</navMap></ncx>')
        z.writestr('OEBPS/Text/ch.xhtml', f'<html><body>{body}</body></html>')


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / 'book.epub'

    def test_nested_ncx_heading_id_and_apply_roundtrip(self):
        make_epub(self.book)
        self.assertEqual(validate_book(self.book), (1, []))
        spec = export_book(self.book)
        self.assertEqual(spec['entries'][0]['block'], 0)
        self.assertEqual(spec['entries'][0]['expect'], 'Chapter')
        apply_one(self.book, spec)
        self.assertEqual(validate_book(self.book), (1, []))
        self.assertEqual(export_book(self.book)['entries'][0]['block'], 0)

    def test_bad_mimetype_and_broken_archive(self):
        make_epub(self.book, mimetype=b'text/plain')
        self.assertIn('invalid mimetype content', validate_book(self.book)[1])
        self.book.write_bytes(b'not a zip')
        self.assertTrue(validate_book(self.book)[1])

    def test_duplicate_dom_blocks_use_identity(self):
        make_epub(self.book, '<p>Same</p><a id="ch"></a><p>Same</p>')
        self.assertEqual(export_book(self.book)['entries'][0]['block'], 1)

    def test_same_block_with_two_anchors_is_shared_target(self):
        make_epub(self.book, '<h1><a id="a"></a><a id="b"></a>Chapter</h1>', [('A','../Text/ch.xhtml#a'),('B','../Text/ch.xhtml#b')])
        self.assertTrue(any('shared' in error for error in validate_book(self.book)[1]))

    def test_reading_order_and_duplicate_ids(self):
        make_epub(self.book, '<h1 id="a">A</h1><h1 id="b">B</h1>', [('B','../Text/ch.xhtml#b'),('A','../Text/ch.xhtml#a')])
        self.assertIn('navigation targets are not in body reading order', validate_book(self.book)[1])
        make_epub(self.book, '<h1 id="ch">A</h1><h1 id="ch">B</h1>')
        self.assertTrue(any('2 matches' in error for error in validate_book(self.book)[1]))

    def test_stale_expect_fails_even_when_coordinates_match(self):
        make_epub(self.book)
        spec = export_book(self.book)
        spec['entries'][0]['expect'] = 'Old chapter'
        with self.assertRaisesRegex(ValueError, 'expected'):
            validate_spec(self.book, spec)

    def test_preflight_rejects_shared_and_reversed_coordinates(self):
        make_epub(self.book, '<h1 id="a">A</h1><h1 id="b">B</h1>', [('A','../Text/ch.xhtml#a'),('B','../Text/ch.xhtml#b')])
        spec = export_book(self.book)
        spec['entries'].reverse()
        with self.assertRaisesRegex(ValueError, 'reading order'):
            validate_spec(self.book, spec)
        spec['entries'] = [spec['entries'][0], dict(spec['entries'][0])]
        with self.assertRaisesRegex(ValueError, 'shared target'):
            validate_spec(self.book, spec)

    def test_corrupt_book_does_not_prevent_corpus_report(self):
        make_epub(self.book)
        (self.root / 'bad.epub').write_bytes(b'broken')
        report = self.root / 'report.csv'
        result = subprocess.run([sys.executable, str(TOOLS / 'validate_epub_toc_acceptance.py'), str(self.root), '--csv-output', str(report)], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('book.epub,1,pass', report.read_text(encoding='utf-8-sig'))
        self.assertIn('bad.epub,0,fail', report.read_text(encoding='utf-8-sig'))

    def test_backup_inside_input_rejected_without_mutation(self):
        make_epub(self.book)
        original = self.book.read_bytes()
        spec = self.root / 'spec.json'
        spec.write_text(json.dumps({'books': [export_book(self.book)]}), encoding='utf-8')
        result = subprocess.run([sys.executable, str(TOOLS / 'apply_epub_toc_coordinates.py'), str(self.root), str(spec), '--evidence-dir', str(self.root/'evidence'), '--backup-dir', str(self.root/'backup'), '--apply'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'outside', result.stderr)
        self.assertEqual(self.book.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
