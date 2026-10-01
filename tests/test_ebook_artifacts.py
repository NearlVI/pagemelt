from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ebook_artifacts import check, sha256, verified_copy
from test_epub_acceptance import make_epub


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.epub'
        self.target = self.root / 'target.epub'
        self.backups = self.root / 'backups'
        make_epub(self.source)

    def test_checks_archive_and_azw3_header(self):
        check(self.source)
        self.target.write_bytes(b'nonempty but broken')
        with self.assertRaises(Exception):
            check(self.target)
        azw = self.root / 'book.azw3'
        azw.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'AZW3'):
            check(azw)

    def test_replacement_backed_up_and_same_copy_is_noop(self):
        self.target.write_bytes(b'old ebook')
        digest = verified_copy(self.source, self.target, self.backups)
        self.assertEqual(digest, sha256(self.target))
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'old ebook')
        verified_copy(self.source, self.target, self.backups)
        self.assertEqual(list(self.backups.iterdir()), backups)

    def test_failed_replace_keeps_original_and_cleans_staging(self):
        self.target.write_bytes(b'old ebook')
        with patch('ebook_artifacts.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                verified_copy(self.source, self.target, self.backups)
        self.assertEqual(self.target.read_bytes(), b'old ebook')
        self.assertFalse(list(self.root.glob('.pdfcracker-*')))


if __name__ == '__main__':
    unittest.main()
