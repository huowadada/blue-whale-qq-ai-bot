# -*- coding: utf-8 -*-
"""心情：实时变化，影响语气。"""
import io, os, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'mood.json')

# 激活与衰减：每种情绪有自己的半衰期（秒）
STIMULI = {
    '被夸': ('开心', +12, 3600), '被骂': ('生气', -18, 1800),
    '被念叨': ('开心', +8, 2400), '被冷落': ('委屈', -10, 5400),
    '被追问': ('烦', -6, 900), '玩梗': ('开心', +6, 1800),
    '被疑似AI': ('烦', -8, 1800),
}


def _load():
    try:
        return json.load(io.open(DB, encoding='utf-8'))
    except Exception:
        return {'value': 60, 'label': '平静', 'ts': int(time.time()), 'log': []}


def _save(d):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    json.dump(d, io.open(DB, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def _decay(d):
    """随时间回到平静（55）"""
    now = int(time.time())
    mins = max(0, (now - int(d.get('ts') or now))) / 60.0
    v = float(d.get('value', 60))
    v += (58 - v) * min(1.0, mins / 120.0)
    d['value'] = round(v, 1)
    d['ts'] = now
    return d


def current():
    d = _decay(_load())
    _save(d)
    return {'value': d['value'], 'label': label(d['value'])}


def label(v):
    v = float(v)
    if v >= 85:
        return '很开心'
    if v >= 70:
        return '开心'
    if v >= 55:
        return '平静'
    if v >= 40:
        return '低落'
    if v >= 25:
        return '烦'
    return '生气'


def shift(stimulus):
    d = _decay(_load())
    if stimulus in STIMULI:
        lab, dv, _ = STIMULI[stimulus]
        d['value'] = max(0.0, min(100.0, float(d.get('value', 60)) + dv))
        d['label'] = lab
        d.setdefault('log', []).append({'ts': int(time.time()), 'what': stimulus, 'v': d['value']})
        d['log'] = d['log'][-200:]
    d['ts'] = int(time.time())
    _save(d)
    return current()


def describe():
    """给模型看的一句话（不要直接发出去 ✗）"""
    c = current()
    return '你现在心情：' + c['label'] + '（' + str(c['value']) + '/100）。语气要跟着心情走。'
