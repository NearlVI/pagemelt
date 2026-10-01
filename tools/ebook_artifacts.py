"""Check, publish and synchronize ebook files with backups and SHA-256 receipts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_epub_toc_integrity import get_opf_path, html_spine, OPF_NS
from epub_navigation import resolve_href


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def check(path: Path) -> None:
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f'Missing or empty ebook: {path}')
    if path.suffix.lower() == '.azw3':
        with path.open('rb') as handle:
            header = handle.read(100)
        if len(header) < 100 or header[60:68] != b'BOOKMOBI':
            raise ValueError(f'Invalid AZW3 header: {path}')
    elif path.suffix.lower() == '.epub':
        with zipfile.ZipFile(path) as epub:
            infos = epub.infolist()
            if infos[0].filename != 'mimetype' or infos[0].compress_type != zipfile.ZIP_STORED:
                raise ValueError(f'Invalid EPUB mimetype placement: {path}')
            if epub.read('mimetype') != b'application/epub+zip':
                raise ValueError(f'Invalid EPUB mimetype: {path}')
            if len(set(epub.namelist())) != len(infos) or epub.testzip():
                raise ValueError(f'Damaged EPUB archive: {path}')
            opf = get_opf_path(epub)
            root = ET.fromstring(epub.read(opf))
            for item in root.findall('opf:manifest/opf:item', OPF_NS):
                name, _ = resolve_href(item.attrib['href'], opf)
                if name not in epub.namelist():
                    raise ValueError(f'Missing manifest resource {name}: {path}')
            spine = html_spine(epub)
            if not spine or any(name not in epub.namelist() for name in spine):
                raise ValueError(f'Missing EPUB body: {path}')
    else:
        raise ValueError(f'Unsupported ebook format: {path}')


def verified_copy(source: Path, target: Path, backup_dir: Path) -> str:
    """Stage beside destination; preserve any differing old file before replacement."""
    digest = sha256(source)
    if source.resolve() == target.resolve() or (target.is_file() and sha256(target) == digest):
        return digest
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pdfcracker-', suffix=target.suffix, dir=target.parent)
    os.close(fd)
    staged = Path(name)
    try:
        shutil.copy2(source, staged)
        if sha256(staged) != digest:
            raise ValueError(f'Copy verification failed: {target}')
        if target.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f'{uuid.uuid4().hex}-{target.name}'
            shutil.copy2(target, backup)
            if sha256(backup) != sha256(target):
                raise ValueError(f'Backup verification failed: {target}')
            print(f'Backup: {backup}')
        os.replace(staged, target)
        if sha256(target) != digest:
            raise ValueError(f'Published hash mismatch: {target}')
    finally:
        staged.unlink(missing_ok=True)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'sync', 'publish'])
    parser.add_argument('paths', type=Path, nargs='+')
    parser.add_argument('--source-pdf', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--provenance', type=Path, help='Verified build provenance (publish only)')
    args = parser.parse_args()
    provenance = None
    if args.command != 'check':
        if not args.source_pdf or not args.source_pdf.is_file() or args.source_pdf.suffix.lower() != '.pdf':
            parser.error('sync/publish requires an existing --source-pdf')
        if not args.backup_dir:
            parser.error('sync/publish requires --backup-dir')
        if args.command == 'publish' and not args.output_dir:
            parser.error('publish requires --output-dir')
        formats = [path.suffix.lower() for path in args.paths]
        if len(set(formats)) != len(formats):
            parser.error('provide at most one ebook per format')
    if args.provenance:
        if args.command != 'publish' or not args.receipt:
            parser.error('--provenance requires publish and --receipt')
        provenance = json.loads(args.provenance.read_text(encoding='utf-8'))
        if (provenance.get('version') != 1 or not provenance.get('build_config')
                or provenance.get('source_sha256') != sha256(args.source_pdf)):
            parser.error('build provenance does not match current source PDF')
    for path in args.paths:
        check(path)
    rows = []
    for path in args.paths:
        if args.command == 'check':
            print(f'VALID {path}')
            continue
        name = args.source_pdf.stem + path.suffix.lower()
        canonical = args.output_dir / name if args.command == 'publish' else path
        if args.command == 'publish':
            verified_copy(path, canonical, args.backup_dir)
        source_copy = args.source_pdf.with_suffix(path.suffix.lower())
        digest = verified_copy(canonical, source_copy, args.backup_dir)
        rows.append({'canonical': str(canonical.resolve()), 'source_copy': str(source_copy.resolve()), 'sha256': digest})
        print(f'VERIFIED {canonical} -> {source_copy} SHA256={digest}')
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        # Import here to avoid the shared hash/check helper's import cycle.
        from conversion_provenance import write_json
        write_json(args.receipt, {'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
                                 'source_pdf': str(args.source_pdf.resolve()) if args.source_pdf else None,
                                 'source_sha256': sha256(args.source_pdf) if args.source_pdf else None,
                                 'conversion_provenance': provenance, 'artifacts': rows})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
