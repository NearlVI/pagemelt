"""Build the explicitly reviewed September 2026 psychology revision in a new directory.

Decisions are recorded in docs/psychology-review-20260911.md. This never infers
headings or overwrites the original corpus/specification.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from apply_epub_toc_coordinates import flatten, validate_spec, write_zip_entry
from epub_navigation import content_nodes
from export_epub_toc_coordinates import export_book

# One-based NCX item -> (old recorded block, reviewed actual block).
CORRECTIONS = {
    '01隐秘的人格': {97: (79, 103)},
    'Rowland Miller, 王伟平 - 亲密关系': {34: (191,348), 76:(207,401), 90:(207,574), 179:(141,331), 210:(0,142), 230:(0,311), 240:(0,459)},
    '图式治疗': {32:(95,291), 51:(204,471), 52:(298,477), 55:(204,730), 82:(356,926)},
    '循环提问': {5:(2,46)},
    '心理营养': {20:(1,297)},
    '精神分析诊断': {132:(70,122), 133:(88,132)},
    '自闭症的实证干预': {34:(1,30), 86:(64,218), 87:(66,221), 95:(64,326), 96:(66,328), 113:(79,276), 114:(82,278), 122:(79,404), 123:(82,411)},
    '认知疗法：进阶与挑战': {47:(45,80), 66:(50,266)},
}

# Missing headings confirmed against original PDF pages 16, 98, 152, 210;
# appendix heading confirmed from the embedded title image.
HEADINGS = {
    '[完美伴侣': [
        ('ebook_source_split_006.html',31,2,'第1章 现代人不懂真正的性爱','贪图眼前欢'),
        ('ebook_source_split_006.html',411,22,'第2章 男人和女人的根本区别','女人其实不懂得真正的鱼水之欢'),
        ('ebook_source_split_007.html',105,37,'第3章 来做缓慢性爱吧','矫枉过正'),
        ('ebook_source_split_007.html',369,52,'第4章 亚当性爱理论与技巧','放松心情'),
    ],
    '做自己的咨询师': [
        ('ebook_source_split_008.html',982,28,'附录','附录一 美人技术系列指导'),
    ],
}


def prepare(source: Path, target: Path, spec: dict) -> dict:
    revised = copy.deepcopy(spec)
    entries = flatten(revised['entries'])
    actual = flatten(export_book(source)['entries'])
    assert len(entries) == len(actual), source.name
    expected_changes = next((v for k,v in CORRECTIONS.items() if source.name.startswith(k)), {})
    for i, (old, observed) in enumerate(zip(entries, actual), 1):
        assert old['label'] == observed['label'] and old['file'] == observed['file']
        if i in expected_changes:
            before, after = expected_changes[i]
            assert old['block'] == before and observed['block'] == after, (source.name,i)
            assert old['expect'] == observed['expect'], (source.name,i,'text changed')
            old['block'] = after
        else:
            assert old['block'] == observed['block'], (source.name,i,'unreviewed drift')

    if source.name.startswith('情绪的语言'):
        assert entries[1]['label'] == '第一篇 重拾与生俱来的语言'
        assert entries[2]['label'] == '第1章 导言'
        entries[1].update(file='ebook_source_split_005.html',block=5,expect='第一篇')
        entries[2].update(file='ebook_source_split_006.html',block=0,expect='第1章 导言')

    headings = next((v for k,v in HEADINGS.items() if source.name.startswith(k)), [])
    if not headings:
        shutil.copy2(source, target)
    else:
        updates = {}
        with zipfile.ZipFile(source) as z:
            for name in {h[0] for h in headings}:
                soup = BeautifulSoup(z.read(name), 'lxml')
                nodes = content_nodes(soup)
                for _, block, item, title, expect in (h for h in headings if h[0] == name):
                    assert entries[item-1]['label'] == title
                    assert expect in nodes[block].get_text(' ', strip=True)
                    heading = soup.new_tag('h1')
                    heading.string = title
                    nodes[block].insert_before(heading)
                updates[name] = soup.encode('utf-8', formatter='minimal')
            with zipfile.ZipFile(target, 'w') as out:
                for info in z.infolist():
                    write_zip_entry(out, info, updates.get(info.filename, z.read(info.filename)))
        for entry in entries:
            entry['block'] += sum(1 for name,block,_,_,_ in headings if entry['file']==name and block<=entry['block'])
        for name,block,item,title,_ in headings:
            entries[item-1].update(file=name,block=block+sum(1 for n,b,_,_,_ in headings if n==name and b<block),expect=title)
    validate_spec(target, revised)
    return revised


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('original_spec', type=Path)
    parser.add_argument('staging_dir', type=Path)
    parser.add_argument('output_spec', type=Path)
    args = parser.parse_args()
    if args.staging_dir.exists() or args.output_spec.exists():
        parser.error('staging directory and output spec must be new paths')
    data = json.loads(args.original_spec.read_text(encoding='utf-8'))
    args.staging_dir.mkdir(parents=True)
    revised = []
    for book in data['books']:
        revised.append(prepare(args.input_dir/book['file'],args.staging_dir/book['file'],book))
    payload = {'version': 2, 'description': 'Reviewed correction of DOM identity coordinates and five source-confirmed missing headings; September 2026.', 'books':revised}
    args.output_spec.parent.mkdir(parents=True, exist_ok=True)
    args.output_spec.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Prepared {len(revised)} books. Next: validate -> apply with backups -> accept before publication.')


if __name__ == '__main__':
    main()
