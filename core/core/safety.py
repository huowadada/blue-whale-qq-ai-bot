# -*- coding: utf-8 -*-
"""安全：关键词、外链隔离、信任域名、拉黑策略。
★ 参考那个库的做法：**只解析文字，绝不访问链接** ✓"""
import os, re, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, 'data', 'safety.log')

BAD_WORDS = ['开盒', '人肉', '身份证', '手机号', '住址',
             '杀你', '弄死你', '血洗', '国家领导',
             '成人片', '裸聊', '加微', '加V', '下注', '博彩']

DEFAULT_TRUSTED = ['bilibili.com', 'b23.tv', 'hdslb.com']


def extract_links(text):
    return re.findall(r'https?://[^\s\"\'<>)]+', str(text or ''))


def links_trusted(text, trusted=None):
    """所有链接是否都在信任域名内（不访问 ✓）"""
    tr = [d.lower() for d in (trusted or DEFAULT_TRUSTED)]
    for u in extract_links(text):
        host = re.sub(r'^https?://', '', u).split('/')[0].split(':')[0].lower()
        if not any(host == d or host.endswith('.' + d) for d in tr):
            return False
    return True


def is_safe(text, trusted=None):
    t = str(text or '')
    low = t.lower()
    for w in BAD_WORDS:
        if w.lower() in low:
            return {'safe': False, 'why': '命中敏感词：' + w}
    # 裸 IP / 非信任外链 / 引流暗号
    if re.search(r'\b\d{1,3}(\.\d{1,3}){3}\b', t):
        return {'safe': False, 'why': '出现 IP 地址'}
    if not links_trusted(t, trusted):
        return {'safe': False, 'why': '出现非信任外链'}
    if re.search(r'(?i)(vx|wx|qq)\s*[:\uff1a]?\s*\d{5,}', t):
        return {'safe': False, 'why': '疑似引流联系方式'}
    return {'safe': True, 'why': ''}


def quarantine(where, uid, text, why):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    rec = {'ts': int(time.time()), 'where': where, 'uid': str(uid), 'why': why, 'text': str(text)[:300]}
    with io.open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


import io  # noqa: E402
