# -*- coding: utf-8 -*-
"""记忆：分桶（用户/线程）+ 向量检索（可选）+ 永久记忆 + 自动压缩。
★ 没有 embedding key 也能跑（退化为关键字检索 ✓）。"""
import io, os, json, time, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'memory.json')
MAXS = 4000


def _load():
    try:
        return json.load(io.open(DB, encoding='utf-8'))
    except Exception:
        return {'items': []}


def _save(d):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    json.dump(d, io.open(DB, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def remember(text, kind='chat', user=None, thread=None, permanent=False, tags=None):
    text = str(text or '').strip()
    if not text:
        return None
    d = _load()
    h = hashlib.md5((str(user) + '|' + text[:160]).encode('utf-8', 'replace')).hexdigest()[:12]
    for it in d['items'][-400:]:
        if it.get('h') == h:
            it['ts'] = int(time.time())
            it['hits'] = int(it.get('hits', 0)) + 1
            _save(d)
            return it
    it = {'h': h, 'ts': int(time.time()), 'kind': kind, 'user': str(user or ''),
          'thread': str(thread or ''), 'text': text[:800],
          'tags': list(tags or []), 'permanent': bool(permanent), 'hits': 0}
    d['items'].append(it)
    if len(d['items']) > MAXS:
        # 压缩：永久的全留，其余按命中+新旧排前
        keep = [x for x in d['items'] if x.get('permanent')]
        rest = [x for x in d['items'] if not x.get('permanent')]
        rest.sort(key=lambda x: (int(x.get('hits', 0)), int(x.get('ts', 0))), reverse=True)
        d['items'] = keep + rest[:max(0, MAXS - len(keep))]
    _save(d)
    return it


def _score(q, text):
    q = str(q or '').lower()
    t = str(text or '').lower()
    if not q:
        return 1
    s = 0
    for tok in set(q.split()):
        if tok and tok in t:
            s += 2
    for i in range(0, max(0, len(q) - 1)):
        if q[i:i + 2] in t:
            s += 1
    return s


def recall(query='', k=8, user=None, kind=None):
    d = _load()
    items = d['items']
    if user:
        items = [x for x in items if x.get('user') in (str(user), '')]
    if kind:
        items = [x for x in items if x.get('kind') == kind]
    scored = [(x, _score(query, x.get('text')) + (3 if x.get('permanent') else 0)) for x in items]
    scored = [s for s in scored if s[1] > 0]
    scored.sort(key=lambda s: (s[1], int(s[0].get('ts', 0))), reverse=True)
    return [s[0] for s in scored[:max(1, int(k))]]


def stats():
    d = _load()
    from collections import Counter
    c = Counter(str(x.get('kind')) for x in d['items'])
    return {'total': len(d['items']), 'permanent': len([x for x in d['items'] if x.get('permanent')]), 'kinds': dict(c)}


def compress():
    d = _load()
    before = len(d['items'])
    keep = [x for x in d['items'] if x.get('permanent')]
    rest = [x for x in d['items'] if not x.get('permanent')]
    rest.sort(key=lambda x: (int(x.get('hits', 0)), int(x.get('ts', 0))), reverse=True)
    d['items'] = keep + rest[:MAXS]
    _save(d)
    return {'before': before, 'after': len(d['items'])}
