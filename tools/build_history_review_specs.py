"""Reviewed Paris chapter labels and Renaissance author/story hierarchy."""

import argparse
import json
from pathlib import Path

from export_epub_toc_coordinates import export_book


def node(label, number, block, expect=None, children=None):
    result={'label':label,'file':f'ebook_source_split_{number:03d}.html','block':block,'expect':expect or label}
    if children:
        result['children']=children
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('epub_dir',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    paris,=args.epub_dir.glob('巴黎神话*.epub')
    satire,=args.epub_dir.glob('诙谐的断代史*.epub')
    labels=[
        '巴黎，第一次现代性的神话之都','巴黎，革命的神话之都','巴黎，罪恶的神秘之都',
        '巴黎女性，反女权主义神话的形成及演变','巴黎，科学之都','巴黎：可读的神话，可见的神话',
        '巴黎－机器：一个现代工业之都的神话','巴黎以及自我异化的反神话',
        '歌剧与轻歌剧：巴黎—纽约 巴黎—伦敦 巴黎—布达佩斯',
        '巴尔扎克、波德莱尔、左拉：19世纪文学想象中的巴黎','巴黎的魔幻：巴黎，娱乐之都',
        '美洲的白人与黑人想象中的巴黎','巴黎世界博览会：从神话到魔幻',
        '超现实主义和老巴黎神话的终结','巴黎在欧洲：巴黎，艺术之都',
    ]
    numbers=['一','二','三','四','五','六','七','八','九','十','十一','十二','十三','十四','十五']
    paris_entries=[node('译者序',1,0),node('引言',1,41)]
    paris_entries.extend(node(f'第{n}章 {label}',i+2,0,f'第{n}章') for i,(n,label) in enumerate(zip(numbers,labels)))
    paris_entries.extend([node('结束语',16,118),node('人名对照表',16,125)])

    stories=export_book(satire)['entries']
    assert len(stories)==299 and not any(e.get('children') for e in stories)
    groups=[
        ('I 波焦·布拉乔利尼',0,179,'波焦·布拉乔利尼',0,68),
        ('II 卢多维科·卡蓬',68,4,'卢多维科·卡蓬',68,75),
        ('III 皮奥瓦诺·阿洛托',75,11,'皮奥瓦诺·阿洛托',75,113),
        ('IV 安吉洛·波利齐亚诺',113,9,'安吉洛·波利齐亚诺',113,164),
        ('V 尼科洛·安杰利·达尔·布奇内',164,4,'尼科洛·安杰利·达尔·布奇内',164,176),
        ('VI 乔万尼·蓬塔诺',176,5,'乔万尼·蓬塔诺',176,193),
        ('VII 列奥纳多·达·芬奇',193,5,'列奥纳多·达·芬奇',193,203),
        ('VIII 卢多维科·多米尼奇',203,3,'卢多维科·多米尼奇',203,284),
        ('IX 卢多维科·圭恰迪尼',284,3,'卢多维科·圭恰迪尼',284,294),
    ]
    satire_entries=[node('导读：诙谐与智慧',0,51),node('导言',0,134)]
    for label,file,block,expect,start,end in groups:
        children=stories[start:end]
        assert all(e['file']==f'ebook_source_split_{i+1:03d}.html' and e['block']==0 for i,e in enumerate(stories[start:end],start)),label
        if start == 164:
            # The seventh story is a plain paragraph between stories 6 and 8;
            # inspected body text confirms both the title and the anecdote.
            children.insert(6,node('7 弗朗西斯科·斯福扎的英勇',170,4,'7 弗朗西斯科·斯福扎的英勇'))
        assert [int(e['label'].split()[0]) for e in children]==list(range(1,len(children)+1)),label
        satire_entries.append(node(label,file,block,expect,children))
    assert [int(e['label'].split()[0]) for e in stories[294:]]==[1,2,3,1,2]
    satire_entries.append(node('X 两位诙谐之士：贡内拉和巴尔拉齐亚',294,3,'两位诙谐之士：贡内拉和巴尔拉齐亚',[
        node('贡内拉',294,9,'贡内拉',stories[294:297]),
        node('巴尔拉齐亚',297,6,'巴尔拉齐亚',stories[297:299]),
    ]))
    satire_entries.append(node('XI 巴尔达萨雷·卡斯蒂廖内',299,7,'巴尔达萨雷·卡斯蒂廖内'))
    args.output.write_text(json.dumps({'books':[{'file':paris.name,'entries':paris_entries},{'file':satire.name,'entries':satire_entries}]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
