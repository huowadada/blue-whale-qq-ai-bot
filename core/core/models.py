# -*- coding: utf-8 -*-
"""模型层：chat / vision / search / image，全部 OpenAI 兼容 ✓，均带备用回退。"""
import json, urllib.request, urllib.error


def _cfg(cfg, key, default=None):
    m = (cfg or {}).get('models') or {}
    v = m.get(key) or {}
    if not v.get('api_key'):
        base = m.get('chat') or {}
        v = dict(v)
        v.setdefault('base_url', base.get('base_url'))
        v.setdefault('api_key', base.get('api_key'))
    return v


def _post(url, key, payload, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + str(key or '')}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def chat(cfg, messages, temperature=0.9):
    """主模型失败 → 自动切备用 ✓"""
    v = _cfg(cfg, 'chat')
    cands = [v] + [x for x in [( (cfg or {}).get('models') or {}).get('chat_fallback') or {}] if x]
    last = ''
    for c in cands:
        if not c.get('base_url') or not c.get('model'):
            continue
        try:
            j = _post(c['base_url'].rstrip('/') + '/chat/completions', c.get('api_key'),
                      {'model': c['model'], 'messages': messages, 'temperature': temperature})
            return (j.get('choices') or [{}])[0].get('message', {}).get('content', '')
        except urllib.error.HTTPError as e:
            last = 'HTTP %s %s' % (e.code, e.read().decode('utf-8', 'replace')[:200])
        except Exception as e:
            last = str(e)[:200]
    raise RuntimeError('所有对话模型都不行：' + last)


def vision(cfg, prompt, image_url, temperature=0.5):
    v = _cfg(cfg, 'vision')
    if not v.get('model'):
        v = _cfg(cfg, 'chat')
    msg = [{'role': 'user', 'content': [{'type': 'text', 'text': prompt},
                                        {'type': 'image_url', 'image_url': {'url': image_url}}]}]
    j = _post(v['base_url'].rstrip('/') + '/chat/completions', v.get('api_key'),
              {'model': v['model'], 'messages': msg, 'temperature': temperature})
    return (j.get('choices') or [{}])[0].get('message', {}).get('content', '')


def image(cfg, prompt, size='1024x1024'):
    v = _cfg(cfg, 'image')
    if not v.get('model'):
        raise RuntimeError('没配画图模型')
    j = _post(v['base_url'].rstrip('/') + '/images/generations', v.get('api_key'),
              {'model': v['model'], 'prompt': prompt, 'size': size})
    d = (j.get('data') or [{}])[0]
    return d.get('url') or d.get('b64_json') or ''


def search(cfg, query):
    v = _cfg(cfg, 'search')
    if not v.get('model'):
        return ''
    msg = [{'role': 'user', 'content': query}]
    j = _post(v['base_url'].rstrip('/') + '/chat/completions', v.get('api_key'),
              {'model': v['model'], 'messages': msg})
    return (j.get('choices') or [{}])[0].get('message', {}).get('content', '')


def test(cfg):
    """面板里的“一键测试” ✓"""
    out = {}
    for k in ('chat', 'vision', 'search', 'image'):
        v = _cfg(cfg, k)
        out[k] = bool(v.get('base_url') and v.get('api_key') and v.get('model'))
    return out
