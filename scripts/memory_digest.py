# -*- coding: utf-8 -*-
"""把 facts.md 压成【摘要】，直接嵌进她的卡片 → 她每轮自动带着 ✓
（细节仍留在 facts.md / memory.md 里，需要时再读 ✓）
用法：python memory_digest.py
"""
import io
import json
import os
import re
import shutil
import time

W = r'C:\Users\28461\Documents\deepseek-harness\default-workspace'
FACTS = os.path.join(W, 'qqbot', 'memory', 'facts.md')
A = os.path.join(W, 'qqbot', 'AGENTS.md')
NOTES = os.path.join(W, 'qqbot', 'bili', 'state', 'notes.json')

BEGIN = '<!-- AUTO-DIGEST:BEGIN 自动生成，勿手改 -->'
END = '<!-- AUTO-DIGEST:END -->'

CAPS = [
    ('群里的人', 7),
    ('发生过的事', 8),
    ('规矩', 8),
    ('黑话', 8),
    ('主人', 3),
    ('坑', 6),
]


def cap_for(name):
    for k, v in CAPS:
        if k in name:
            return v
    return 6


def digest():
    t = io.open(FACTS, encoding='utf-8').read()
    groups = {}
    order = []
    cur = None
    for line in t.splitlines():
        l = line.rstrip()
        if l.startswith('## '):
            cur = l[3:].strip()
            if cur not in groups:
                groups[cur] = []
                order.append(cur)
            continue
        if cur is None or not l.strip() or l.startswith('>'):
            continue
        if l.lstrip().startswith(('-', '*')):
            groups[cur].append(l.strip())
    out = []
    for name in order:
        items = groups[name]
        if not items:
            continue
        out.append('**' + name + '**')
        out.extend(items[:cap_for(name)])
        out.append('')

    # ★ 她自己记的笔记（含联网搜到的 ✓）
    try:
        _n = json.load(io.open(NOTES, encoding='utf-8'))
        _items = _n if isinstance(_n, list) else (_n.get('notes') or _n.get('items') or [])
        _items = [x for x in _items if isinstance(x, dict) and str(x.get('text') or '').strip()]
        _items.sort(key=lambda x: int(x.get('ts') or 0), reverse=True)
        if _items:
            out.append('**她记下的（含联网搜到的）**')
            for _x in _items[:8]:
                _k = str(_x.get('kind') or '')
                out.append('- [' + _k + '] ' + str(_x.get('text'))[:150])
            out.append('')
    except Exception:
        pass
    body = '\n'.join(out).strip()
    if len(body) > 3000:
        body = body[:3000].rsplit('\n', 1)[0] + '\n- （更多细节见 facts.md ✓）'
    return body


def main():
    body = digest()
    nl = chr(10)
    block = (BEGIN + nl + '## ★★★ 开机记忆（自动带着 ✓ 每轮都在 ✓）' + nl + nl
             + body + nl + nl
             + '_(完整版：`qqbot\\memory\\facts.md` ✓ 全部流水：`qqbot\\memory\\memory.md` ✓)_' + nl
             + END + nl)
    s = io.open(A, encoding='utf-8').read()
    if BEGIN in s and END in s:
        s2 = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n', lambda m: block, s, count=1, flags=re.S)
    else:
        i = s.find('## ★★★ 开口前就做这三步')
        if i < 0:
            i = s.find('## ')
        s2 = s[:i] + block + nl + s[i:]
    if s2 != s:
        shutil.copy2(A, A + '.bak-digest-' + time.strftime('%Y%m%d-%H%M%S'))
        io.open(A, 'w', encoding='utf-8').write(s2)
    n_items = sum(1 for l in body.splitlines() if l.lstrip().startswith(('-', '*')))
    print('摘要：%d 行 / %d 字 / %d 条  (~%d token)' % (len(body.splitlines()), len(body), n_items, len(body) // 3))
    print('AGENTS.md 现在 %d 行' % len(s2.splitlines()))


if __name__ == '__main__':
    main()
