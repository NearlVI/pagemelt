from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from conversion_provenance import record_extraction, verify_extraction, verify_outputs, write_json
from ebook_artifacts import sha256
from test_epub_acceptance import make_epub


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / 'book.pdf'
        self.pdf.write_bytes(b'%PDF-original-test-source')
        self.work = self.root / 'work'
        (self.work / 'mineru').mkdir(parents=True)
        (self.work / 'source.pdf').write_bytes(self.pdf.read_bytes())
        self.content = self.work / 'mineru' / 'content.json'
        self.content.write_text('[]', encoding='utf-8')
        self.config = {'backend': 'vlm-engine', 'mineru_version': 'test'}

    def test_extraction_roundtrip_and_identical_source_relocation(self):
        record_extraction(self.pdf, self.work, self.config)
        moved = self.root / 'other.pdf'
        moved.write_bytes(self.pdf.read_bytes())
        verify_extraction(moved, self.work, self.config)

    def test_missing_provenance_rejects_legacy_cache(self):
        with self.assertRaisesRegex(ValueError, 'no provenance'):
            verify_extraction(self.pdf, self.work, self.config)

    def test_changed_source_or_configuration_rejected(self):
        record_extraction(self.pdf, self.work, self.config)
        with self.assertRaisesRegex(ValueError, 'configuration'):
            verify_extraction(self.pdf, self.work, {'backend': 'pipeline'})
        self.pdf.write_bytes(b'%PDF-another-book-with-same-name')
        with self.assertRaisesRegex(ValueError, 'different PDF'):
            verify_extraction(self.pdf, self.work, self.config)

    def test_changed_removed_and_added_extraction_files_rejected(self):
        for mutation in ('change', 'remove', 'add'):
            with self.subTest(mutation=mutation):
                self.content.write_text('[]', encoding='utf-8')
                extra = self.work / 'mineru' / 'extra.json'
                extra.unlink(missing_ok=True)
                record_extraction(self.pdf, self.work, self.config)
                if mutation == 'change':
                    self.content.write_text('[1]', encoding='utf-8')
                elif mutation == 'remove':
                    self.content.unlink()
                else:
                    extra.write_text('[]', encoding='utf-8')
                with self.assertRaises(ValueError):
                    verify_extraction(self.pdf, self.work, self.config)

    def test_changed_source_during_extraction_not_recorded(self):
        self.pdf.write_bytes(b'%PDF-replaced')
        with self.assertRaisesRegex(ValueError, 'changed during'):
            record_extraction(self.pdf, self.work, self.config)
        self.assertFalse((self.work / 'extraction-provenance.json').exists())

    def test_output_requires_source_config_path_and_artifact_hash(self):
        epub = self.root / 'book.epub'
        make_epub(epub)
        receipts = self.root / 'receipts'
        receipts.mkdir()
        (receipts / 'broken.json').write_text('{', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'no matching'):
            verify_outputs(self.pdf, [epub], receipts, self.config)
        record = {'conversion_provenance': {'version': 1, 'source_sha256': sha256(self.pdf),
                                            'build_config': self.config},
                  'artifacts': [{'canonical': str(epub), 'sha256': sha256(epub)}]}
        write_json(receipts / 'valid.json', record)
        verify_outputs(self.pdf, [epub], receipts, self.config)
        with self.assertRaises(ValueError):
            verify_outputs(self.pdf, [epub], receipts, {'backend': 'pipeline'})
        record['artifacts'][0]['sha256'] = 'old-output-hash'
        write_json(receipts / 'valid.json', record)
        with self.assertRaises(ValueError):
            verify_outputs(self.pdf, [epub], receipts, self.config)

    def test_publish_receipt_retains_provenance_and_changed_pdf_is_not_published(self):
        epub = self.root / 'book.epub'
        make_epub(epub)
        provenance = self.root / 'build.json'
        write_json(provenance, {'version': 1, 'source_sha256': sha256(self.pdf),
                                'build_config': self.config})
        receipt = self.root / 'receipt.json'
        output = self.root / 'output'
        cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / 'tools/ebook_artifacts.py'),
               'publish', str(epub), '--source-pdf', str(self.pdf), '--output-dir', str(output),
               '--backup-dir', str(self.root / 'backups'), '--receipt', str(receipt),
               '--provenance', str(provenance)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(receipt.read_text(encoding='utf-8'))['conversion_provenance']['build_config'], self.config)
        before = sha256(output / 'book.epub')
        self.pdf.write_bytes(b'%PDF-new')
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sha256(output / 'book.epub'), before)


if __name__ == '__main__':
    unittest.main()
