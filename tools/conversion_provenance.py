"""Bind reusable extraction and build receipts to PDF bytes and configuration."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import os
import tempfile
from pathlib import Path

from ebook_artifacts import check, sha256

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.provenance-', dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def extraction_config(backend: str, method: str, lang: str, model_source: str) -> dict:
    try:
        version = importlib.metadata.version('mineru')
    except importlib.metadata.PackageNotFoundError:
        version = 'not-installed'
    return {'backend': backend, 'method': method if backend != 'vlm-engine' else None,
            'lang': lang if backend == 'pipeline' else None,
            'model_source': model_source, 'mineru_version': version}


def file_inventory(directory: Path) -> dict[str, str]:
    files = sorted(path for path in directory.rglob('*') if path.is_file())
    if not files:
        raise ValueError(f'No retained extraction files: {directory}')
    return {path.relative_to(directory).as_posix(): sha256(path) for path in files}


def record_extraction(source: Path, work: Path, config: dict) -> dict:
    digest = sha256(source)
    if sha256(work / 'source.pdf') != digest:
        raise ValueError('Source PDF changed during extraction; refusing to record provenance')
    record = {'version': 1, 'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
              'source_pdf': str(source.resolve()), 'source_sha256': digest,
              'extraction_config': config, 'files': file_inventory(work / 'mineru')}
    write_json(work / 'extraction-provenance.json', record)
    return record


def verify_extraction(source: Path, work: Path, config: dict) -> dict:
    manifest = work / 'extraction-provenance.json'
    if not manifest.is_file():
        raise ValueError('Retained extraction has no provenance; rerun without -SkipMinerU')
    record = json.loads(manifest.read_text(encoding='utf-8'))
    if record.get('version') != 1 or record.get('source_sha256') != sha256(source):
        raise ValueError('Retained extraction belongs to different PDF bytes; rerun MinerU')
    if record.get('extraction_config') != config:
        raise ValueError('Retained extraction configuration/version changed; rerun MinerU')
    if sha256(work / 'source.pdf') != record['source_sha256']:
        raise ValueError('Retained source.pdf was modified; rerun MinerU')
    if record.get('files') != file_inventory(work / 'mineru'):
        raise ValueError('Retained extraction files changed or are incomplete; rerun MinerU')
    return record


def build_config(config: dict, title: str, author: str, calibre: Path) -> dict:
    paths = [ROOT / 'scripts/convert-pdfbook.ps1', ROOT / 'tools/mineru_content_to_markdown.py',
             ROOT / 'tools/markdown_to_simple_html.py', ROOT / 'tools/conversion_provenance.py']
    return {'extraction': config, 'title': title, 'author': author,
            'calibre_executable_sha256': sha256(calibre),
            'tools': {path.name: sha256(path) for path in paths}}


def verify_outputs(source: Path, paths: list[Path], receipt_dir: Path, config: dict) -> None:
    digest = sha256(source)
    expected = {}
    for path in paths:
        check(path)
        expected[str(path.resolve()).casefold()] = sha256(path)
    matched = set()
    for receipt in receipt_dir.glob('*.json'):
        try:
            data = json.loads(receipt.read_text(encoding='utf-8'))
            provenance = data.get('conversion_provenance') or {}
            if (provenance.get('version') != 1 or provenance.get('source_sha256') != digest
                    or provenance.get('build_config') != config):
                continue
            for artifact in data.get('artifacts', []):
                key = str(Path(artifact['canonical']).resolve()).casefold()
                if key in expected and artifact.get('sha256') == expected[key]:
                    matched.add(key)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue  # An unrelated damaged receipt cannot attest to this output.
    if matched != set(expected):
        raise ValueError('Existing outputs have no matching source/configuration/hash receipt; '
                         'preserved unchanged. Review them or explicitly use -Force to rebuild')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['record', 'verify', 'build', 'outputs'])
    parser.add_argument('--source-pdf', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--backend', default='vlm-engine')
    parser.add_argument('--method', default='auto')
    parser.add_argument('--lang', default='ch')
    parser.add_argument('--model-source', default='modelscope')
    parser.add_argument('--title', default='')
    parser.add_argument('--author', default='')
    parser.add_argument('--calibre', type=Path)
    parser.add_argument('--receipt-dir', type=Path)
    parser.add_argument('--paths', type=Path, nargs='+')
    args = parser.parse_args()
    if not args.source_pdf.is_file() or args.source_pdf.suffix.lower() != '.pdf':
        parser.error('--source-pdf must be an existing PDF')
    config = extraction_config(args.backend, args.method, args.lang, args.model_source)
    if args.command in ('record', 'verify', 'build') and not args.work_dir:
        parser.error('--work-dir is required')
    if args.command in ('build', 'outputs') and not args.calibre:
        parser.error('--calibre is required')
    if args.command == 'outputs' and (not args.paths or not args.receipt_dir):
        parser.error('--paths and --receipt-dir are required')
    try:
        if args.command == 'record':
            record_extraction(args.source_pdf, args.work_dir, config)
        elif args.command == 'verify':
            verify_extraction(args.source_pdf, args.work_dir, config)
        else:
            build = build_config(config, args.title or args.source_pdf.stem, args.author, args.calibre)
            if args.command == 'build':
                record = verify_extraction(args.source_pdf, args.work_dir, config)
                write_json(args.work_dir / 'build-provenance.json', {
                    'version': 1, 'source_sha256': record['source_sha256'], 'build_config': build,
                    'extraction_manifest_sha256': sha256(args.work_dir / 'extraction-provenance.json')})
            else:
                verify_outputs(args.source_pdf, args.paths, args.receipt_dir, build)
        print(f'PROVENANCE OK: {args.command} {args.source_pdf.name}')
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'PROVENANCE FAILED: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
