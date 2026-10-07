# -*- coding: utf-8 -*-
"""好感度 0~100 + 关系等级 + 用户档案。
参考 bilibili-ai-bot：陌生人→粉丝→熟人→好友→主人；低于阈值/连续辱骂 → 可拉黑。"""
import io, os, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'affection.json')

LEVELS = [(100, '主人'), (80, '好友'), (55, '熟人'), (30, '粉丝'), (0, '陌生人')]


def _load():
    try:
        return json.load(io.open(DB, encoding='utf-8'))
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    json.dump(d, io.open(DB, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def score(uid):
    return int((_load().get(str(uid)) or {}).get('score', 50))


def level(uid):
    s = score(uid)
    for lo, name in LEVELS:
        if s >= lo:
            return name
    return '陌生人'


def bump(uid, delta, reason=''):
    d = _load()
    k = str(uid)
    it = d.setdefault(k, {'score': 50, 'notes': [], 'strikes': 0, 'blocked': False})
    it['score'] = max(-100, min(100, int(it.get('score', 50)) + int(delta)))
    if delta < 0:
        it['strikes'] = int(it.get('strikes', 0)) + 1
    else:
        it['strikes'] = 0
    if reason:
        it.setdefault('notes', []).append({'ts': int(time.time()), 'text': str(reason)[:200], 'delta': delta})
        it['notes'] = it['notes'][-50:]
    it['level'] = level(uid)
    _save(d)
    return it


def profile(uid):
    return _load().get(str(uid)) or {}


def note(uid, text):
    """记一条对这个人的印象"""
    return bump(uid, 0, text)


def top(n=20):
    d = _load()
    items = sorted(d.items(), key=lambda kv: -int((kv[1] or {}).get('score', 0)))[:n]
    return [{'uid': k, 'score': int((v or {}).get('score', 0)), 'level': level(k)} for k, v in items]


def maybe_block(uid, block_below=-30, strikes=5):
    """返回 True 则应该拉黑（真拉黑动作由平台适配器做 ✓）"""
    it = profile(uid)
    if it.get('blocked'):
        return True
    return score(uid) <= block_below or int(it.get('strikes', 0)) >= strikes


def mark_blocked(uid):
    d = _load()
    d.setdefault(str(uid), {'score': 50})['blocked'] = True
    _save(d)
