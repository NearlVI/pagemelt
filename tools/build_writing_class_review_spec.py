"""Explicitly reviewed hierarchy from The Kite and the String's printed contents."""

import argparse
import json
from pathlib import Path


def entry(label, children=(), search=None):
    value = {'label':label,'search':search or label,'exact':True}
    if children:
        value['children'] = [entry(child) if isinstance(child,str) else child for child in children]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('epub_dir',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    matches = list(args.epub_dir.glob('写作课*.epub'))
    if len(matches)!=1:
        parser.error('expected exactly one writing-class book')
    tree = [
        entry('引言：打扰一下，我们是否在哪儿见过？',search='引言'),
        entry('风筝与线',[
            entry('自由写作，但别忽略常识',['故事之声','恰到好处的白日梦']),
        ]),
        entry('让人物行动起来',[
            entry('想象'),
            entry('灵感来了怎么办？',['记录想法','差点儿发生的和本该发生的','脱离现实的杜撰','修辞','从主题到完整的作品']),
            entry('顺其自然',['制造麻烦','戏剧化要有，但别太过','合理运用巧合']),
            entry('成为别人',['我可以假装是你吗？','“她会怎么做？”']),
        ]),
        entry('短篇与长篇：从起点到终点',[
            entry('充分认识短篇与长篇',[
                entry('什么是短篇小说？——以格雷丝·佩利的《和父亲的对话》为例',search='什么是短篇小说？'),
                '蒂莉·奥尔森：《我站在这儿熨烫》','爱德华·P.琼斯：《母亲节后的星期天》',
                '未完成的长篇','长篇小说的构思','《米德尔马契》的故事大纲',
            ]),
            entry('女王的死因，以及“不确定”的吸引力',[
                '篇幅长的就是长篇小说吗？','女王之死','宽阔笔直的单行道','风景优美的观光线路',
                '高速公路','之字形线路','迂回的小径——和孩子玩寻宝游戏',
            ]),
        ]),
        entry('敞开心扉',[
            entry('沉默，还是开口讲出来',[
                '开不了口——作家的写作障碍','直接叙述与间接叙述','有信息量的句子','悬念',
                '沉溺于心理活动的人物','刻意打乱时间顺序','动机不明','无益的脱离现实',
                '省略','为安全而省略','作品中的被动沉默式人物','把故事讲出来',
            ]),
        ]),
        entry('坚持写下去',[
            entry('修正思维的泡泡',[
                '不切实际的幻想','我们应该怎么做？','想清楚究竟想要什么','哪些事不该做？',
                '你的作品足以出版了吗？','修改，但不绝望','寻找读者','通过阅读学写作',
                '在哪里投稿？','如何投稿？','还不行怎么办？','自助出版','兼职作家','保持愉悦','写作那些事儿',
            ]),
        ]),
        entry('致谢'),
    ]
    data = {'books':[{'file':matches[0].name,'start_file':1,'start_block':96,'entries':tree}]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
