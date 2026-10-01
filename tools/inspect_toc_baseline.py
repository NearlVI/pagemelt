"""Read-only coordinate drift evidence for an existing reviewed specification."""

import argparse
import json
import zipfile
from collections import defaultdict
from pathlib import Path

from apply_epub_toc_coordinates import blocks, flatten
from export_epub_toc_coordinates import export_book


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('epub_dir', type=Path)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = []
    for book in json.loads(args.spec.read_text(encoding='utf-8'))['books']:
        path = args.epub_dir / book['file']
        actual = flatten(export_book(path)['entries'])
        expected = flatten(book['entries'])
        changes = []
        groups = defaultdict(list)
        with zipfile.ZipFile(path) as epub:
            cache = {}

            def context(entry):
                name, block = entry['file'], entry['block']
                if name not in cache:
                    cache[name] = blocks(epub.read(name))
                return [{'block': i, 'text': text[:180]} for i, (_, text) in enumerate(cache[name]) if abs(i-block) <= 1]

            for i, (old, new) in enumerate(zip(expected, actual), 1):
                groups[(new['file'], new['block'])].append(new['label'])
                if (old['file'], old['block']) != (new['file'], new['block']):
                    changes.append({'item': i, 'label': new['label'], 'old_file': old['file'], 'new_file': new['file'], 'old': context(old), 'actual': context(new)})
            shared = [{'file': name, 'block': block, 'labels': labels, 'context': context({'file':name, 'block':block})} for (name,block),labels in groups.items() if len(labels)>1]
        if changes or shared or len(actual) != len(expected):
            report.append({'book': book['file'], 'expected_items': len(expected), 'actual_items': len(actual), 'coordinate_differences': changes, 'shared_blocks': shared})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'{len(report)} books need review; evidence: {args.output}')


if __name__ == '__main__':
    main()
