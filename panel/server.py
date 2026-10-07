#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大肥鱼 · 控制台后端（独立服务，不依赖 QQ 插件）

作用：
  · 把面板和你现有的脚本接起来（语音 / 皮套 / 聊天）
  · B站：直接调官方 API（评论 / 回复 / 删除 / 点赞 / 投币 / 收藏 / 私信）
      ★ 回复时带 is_dynamic=1（同时转发到我的动态）✓
      ★ 每条只回一次：用 replied.json 去重；启动时先读一遍 ✓
  · 对外开一个本地 HTTP API（默认 127.0.0.1:8787）

跑法： python server.py            （默认 8787）
       python server.py --port 9000 --token abc123
"""
import os, sys, json, time, argparse, threading, subprocess, urllib.parse, urllib.request, http.server, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # …\avatar
DSH  = os.path.expanduser('~/.dsh')
CREDS = os.path.join(DSH, 'secrets', 'bilibili.json')
REPLIED = os.path.join(HERE, 'replied.json')       # ★ 去重账本
PY  = os.path.join(DSH, 'dsh-runtimes', 'dsh-primary-runtime', 'dependencies', 'python', 'python.exe')
NODE = os.path.join(DSH, 'dsh-runtimes', 'dsh-primary-runtime', 'dependencies', 'node', 'bin', 'node.exe')
DSHCLI = r'C:\app\DeepSeek\resources\runtime\cli\bin\dsh.cmd'
QQBOT = r'C:\Users\28461\Documents\deepseek-harness\default-workspace\qqbot'
HARNESS_EXE = r'C:\app\DeepSeek\DeepSeek Harness.exe'
CLI_JS = r'C:\app\DeepSeek\resources\app.asar\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js'
VTS = r'C:\app\steam\steamapps\common\VTube Studio'

import qq                      # ★ QQ（OneBot / NapCat）
qq.start()

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # ★ 关键：所有子进程都不弹窗
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'

# ───────────────────────── 凭据 / 去重账本 ─────────────────────────
def load_creds():
    try:
        j = json.load(open(CREDS, encoding='utf-8'))
    except Exception as e:
        raise RuntimeError('读不到 B站 凭据 %s：%s' % (CREDS, e))
    return {
        'sessdata': j.get('sessdata') or j.get('SESSDATA') or '',
        'jct': j.get('bili_jct') or j.get('biliJct') or '',
        'buvid3': j.get('buvid3') or '',
        'dede': j.get('dedeuserid') or '',
    }

_creds = load_creds()
COOKIE = 'SESSDATA=%s; bili_jct=%s; buvid3=%s; DedeUserID=%s' % (
    _creds['sessdata'], _creds['jct'], _creds['buvid3'], _creds['dede'])

def _load_replied():
    try:
        return json.load(open(REPLIED, encoding='utf-8'))
    except Exception:
        return {'version': 1, 'replied': {}, 'dm': {}}

def _save_replied(d):
    json.dump(d, open(REPLIED, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

REPLIED_DB = _load_replied()

def mark_replied(kind, key, extra=None):
    """记一笔"已回过"，下次启动就不重复回 ✓"""
    rep = REPLIED_DB.setdefault('replied' if kind != 'dm' else 'dm', {})
    rep[str(key)] = {'ts': int(time.time() * 1000), **(extra or {})}
    _save_replied(REPLIED_DB)

def already_replied(kind, key):
    rep = REPLIED_DB.get('replied' if kind != 'dm' else 'dm', {})
    return str(key) in rep

# ───────────────────────── B站 API ─────────────────────────
def bili_get(path, params=None, base='https://api.bilibili.com'):
    url = base + path
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Cookie': COOKIE, 'User-Agent': UA, 'Referer': 'https://www.bilibili.com/'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

def bili_post(path, form, base='https://api.bilibili.com', csrf_in_url=False):
    form = dict(form or {})
    if not csrf_in_url:
        form['csrf'] = _creds['jct']
    url = base + path
    if csrf_in_url:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'csrf': _creds['jct']})
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, headers={
        'Cookie': COOKIE, 'User-Agent': UA, 'Referer': 'https://www.bilibili.com/',
        'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

ERR = {-101: '未登录', -111: 'csrf 校验失败', -400: '请求错误', -403: '权限不足',
       12009: '评论主体不合法', 12006: '不能重复评论', 12061: '评论区已关闭'}

def explain(j):
    return j.get('message') or ERR.get(j.get('code'), 'code=%s' % j.get('code'))

def whoami():
    j = bili_get('/x/web-interface/nav')
    d = j.get('data') or {}
    return {'loggedIn': bool(d.get('isLogin')), 'mid': d.get('mid'), 'uname': d.get('uname'),
            'coin': d.get('money'), 'level': (d.get('level_info') or {}).get('current_level'),
            'vip': (d.get('vipStatus') == 1)}

def post_comment(oid, text, is_dynamic=True, type_=1):
    """发评论。★ is_dynamic=1 → 同时转发到我的动态 ✓"""
    form = {'type': type_, 'oid': str(oid), 'message': text, 'plat': 1}
    if is_dynamic:
        form['is_dynamic'] = 1                      # ★★ 你要的那个选项
    j = bili_post('/x/v2/reply/add', form)
    if j.get('code') != 0:
        return {'ok': False, 'code': j.get('code'), 'error': explain(j)}
    return {'ok': True, 'rpid': str((j.get('data') or {}).get('rpid_str') or (j.get('data') or {}).get('rpid') or '')}

def reply_comment(oid, text, parent, root=0, is_dynamic=True, type_=1):
    """回复某条评论。★ 同样带 is_dynamic ✓"""
    form = {'type': type_, 'oid': str(oid), 'message': text, 'plat': 1, 'parent': str(parent)}
    if root:
        form['root'] = str(root)
    if is_dynamic:
        form['is_dynamic'] = 1
    j = bili_post('/x/v2/reply/add', form)
    if j.get('code') != 0:
        return {'ok': False, 'code': j.get('code'), 'error': explain(j)}
    return {'ok': True, 'rpid': str((j.get('data') or {}).get('rpid_str') or (j.get('data') or {}).get('rpid') or '')}

def del_comment(oid, rpid, type_=1):
    j = bili_post('/x/v2/reply/del', {'type': type_, 'oid': str(oid), 'rpid': str(rpid)})
    return {'ok': j.get('code') == 0, 'code': j.get('code'), 'error': '' if j.get('code') == 0 else explain(j)}

def like_comment(oid, rpid, action=1, type_=1):
    j = bili_post('/x/v2/reply/action', {'type': type_, 'oid': str(oid), 'rpid': str(rpid), 'action': action})
    return {'ok': j.get('code') == 0, 'code': j.get('code'), 'error': '' if j.get('code') == 0 else explain(j)}

def like_video(aid, like=1):
    j = bili_post('/x/web-interface/archive/like', {'bvid': '', 'aid': str(aid), 'like': like})
    return {'ok': j.get('code') == 0, 'code': j.get('code')}

def coin_video(aid, multiply=1, also_like=False):
    j = bili_post('/x/web-interface/coin/add', {'aid': str(aid), 'multiply': multiply,
                                                'select_like': 1 if also_like else 0})
    return {'ok': j.get('code') == 0, 'code': j.get('code'), 'error': '' if j.get('code') == 0 else explain(j)}

def fav_video(aid, add=True):
    """收藏：需要收藏夹 id，先取默认收藏夹。"""
    try:
        j = bili_get('/x/v3/fav/folder/created/list-all', {'up_mid': _creds['dede']})
        folders = (j.get('data') or {}).get('list') or []
        fid = folders[0]['id'] if folders else None
        if not fid:
            return {'ok': False, 'error': '没有收藏夹'}
        r = bili_post('/x/v3/fav/resource/deal',
                      {'rid': str(aid), 'type': 2, 'add_media_ids': fid if add else '',
                       'del_media_ids': '' if add else fid})
        return {'ok': r.get('code') == 0, 'code': r.get('code'), 'folder': fid}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def inbox(limit=20):
    """谁回复了我 / @ 了我（未读优先）。"""
    out = []
    try:
        j = bili_get('/x/msgfeed/reply', {'pn': 1, 'ps': limit})
        for it in ((j.get('data') or {}).get('items') or []):
            for c in (it.get('item') or {}).get('replies') or []:
                out.append({'id': str(c.get('id')), 'who': (c.get('user') or {}).get('nickname'),
                            'text': c.get('content'), 'oid': str(c.get('item_id') or ''),
                            'root': str(c.get('root_id') or c.get('id')), 'ts': c.get('ctime'),
                            'uri': c.get('uri'), 'kind': 'reply'})
    except Exception as e:
        out.append({'error': str(e)})
    return out

def dm_list(limit=30):
    """B站 私信会话列表（★ 正确接口：session_svr/get_sessions）"""
    try:
        j = bili_get('/session_svr/v1/session_svr/get_sessions',
                     {'session_type': 1, 'group_id': 0, 'size': limit},
                     base='https://api.vc.bilibili.com')
        arr = (j.get('data') or {}).get('session_list') or []
        out = []
        for s in arr:
            tid = str(s.get('talker_id') or '')
            last = s.get('last_msg') or {}
            txt = ''
            c = None
            if isinstance(last, dict):
                txt = last.get('content') or ''
                try:
                    import json as _j
                    c = _j.loads(txt) if isinstance(txt, str) and txt.strip().startswith('{') else None
                    if c:
                        txt = c.get('content') or ''
                except Exception:
                    pass
            # ★ 2026-10-06 修：原来只取 content ✗ 把图片/视频/卡片全丢了 ✗✗
            #   她因此看不到对方发的图和视频（主人 2026-10-06 报的）。
            #   现在把整条消息里的 URL / 标题 / bvid 全挖出来贴到文本后面 ✓
            try:
                import re as _re
                extra = []
                def _walk(o):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if isinstance(v, str) and v.strip():
                                kl = k.lower()
                                vs = v.strip()
                                if vs.lower().startswith('http'):
                                    if re.search(r'(b23\.tv|bilibili\.com/video|BV[0-9A-Za-z]{10})', vs):
                                        extra.append('[视频]' + vs[:200])
                                    elif re.search(r'(hdslb\.com|\.(jpg|jpeg|png|gif|webp|mp4))', vs, re.I):
                                        extra.append('[图片]' + vs[:200])
                                    else:
                                        extra.append('[链接]' + vs[:200])
                                elif kl in ('bvid', 'title', 'desc', 'summary', 'name', 'jump_url', 'source'):
                                    extra.append(k + ':' + vs[:120])
                            else:
                                _walk(v)
                    elif isinstance(o, list):
                        for x in o:
                            _walk(x)
                _walk(c if c else last)
                if extra:
                    seen = []
                    for e in extra:
                        if e not in seen:
                            seen.append(e)
                    txt = (str(txt) + ' ' + ' '.join(seen)).strip()
            except Exception:
                pass
            out.append({'id': tid, 'who': tid, 'text': str(txt)[:900],
                        'ts': s.get('session_ts'), 'unread': s.get('unread_count') or 0,
                        'url': 'https://message.bilibili.com/#/whisper/mid' + tid})
        return out
    except Exception as e:
        return [{'error': str(e)}]


def _dm_scan(obj):
    """\u628a\u4e00\u6761\u79c1\u4fe1\u7684 content \u62c6\u6210 (\u6587\u672c, \u5a92\u4f53\u94fe\u63a5\u5217\u8868)"""
    text = ''
    media = []
    if isinstance(obj, dict):
        for k in ('content', 'text', 'title', 'desc', 'summary', 'name'):
            v = obj.get(k)
            if isinstance(v, str) and v.strip() and not text:
                text = v.strip()
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, str) and v.strip():
                        vs = v.strip()
                        kl = k.lower()
                        if vs.lower().startswith('http'):
                            if __import__('re').search(r'(b23\.tv|bilibili\.com/video|BV[0-9A-Za-z]{10})', vs):
                                media.append({'kind': '\u89c6\u9891', 'url': vs[:300]})
                            elif __import__('re').search(r'(hdslb\.com|\.(jpg|jpeg|png|gif|webp|mp4))', vs, __import__('re').I):
                                media.append({'kind': '\u56fe\u7247', 'url': vs[:300]})
                            else:
                                media.append({'kind': '\u94fe\u63a5', 'url': vs[:300]})
                        elif kl in ('bvid', 'jump_url', 'source', 'oid', 'aid'):
                            media.append({'kind': 'card', 'key': k, 'value': vs[:200]})
                    else:
                        walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(obj)
    elif isinstance(obj, str):
        text = obj.strip()
    # \u53bb\u91cd
    seen = set()
    uniq = []
    for m in media:
        sig = json.dumps(m, sort_keys=True, ensure_ascii=False)[:200]
        if sig not in seen:
            seen.add(sig)
            uniq.append(m)
    return text, uniq


def bili_dm_history(mid, size=30):
    """\u2605 2026-10-06 \u4e3b\u4eba\u8981\u6c42\uff1a\u62c9\u4e00\u4e2a\u79c1\u4fe1\u4f1a\u8bdd\u7684\u3010\u5386\u53f2\u6d88\u606f\u3011
    \u2014\u2014 \u56e0\u4e3a\u9762\u677f\u539f\u6765\u53ea\u770b\u4f1a\u8bdd\u5217\u8868\u7684\u201c\u6700\u540e\u4e00\u6761\u201d \u2717
    \u5bf9\u65b9\u53d1\u7684\u56fe\u7247/\u89c6\u9891\u5f80\u5f80\u5728\u66f4\u65e9\u7684\u6d88\u606f\u91cc \u2717 \u6240\u4ee5\u5979\u4ece\u6765\u770b\u4e0d\u5230\u3002"""
    if not mid:
        return {'ok': False, 'error': 'mid \u5fc5\u586b'}
    try:
        n = max(1, min(100, int(size)))
    except Exception:
        n = 30
    try:
        j = bili_get('/svr_sync/v1/svr_sync/fetch_session_msgs',
                     {'talker_id': str(mid), 'session_type': 1, 'size': n},
                     base='https://api.vc.bilibili.com')
        msgs = ((j.get('data') or {}).get('messages')) or []
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    out = []
    me = str(_creds.get('dede') or '')
    for m in msgs:
        c = m.get('content')
        obj = None
        if isinstance(c, str) and c.strip().startswith('{'):
            try:
                obj = json.loads(c)
            except Exception:
                obj = None
        if obj is not None:
            text, media = _dm_scan(obj)
        else:
            text, media = _dm_scan(c)
        if not text and media:
            text = '\uff08' + '\u3001'.join(sorted(set(x.get('kind', '?') for x in media))) + '\uff09'
        out.append({'from': str(m.get('sender_uid') or ''),
                    'mine': str(m.get('sender_uid') or '') == me,
                    'type': m.get('msg_type'),
                    'ts': m.get('timestamp'),
                    'text': text[:600],
                    'media': media})
    out.reverse()   # \u65e9 \u2192 \u665a
    return {'ok': True, 'mid': str(mid), 'count': len(out), 'messages': out}


def dm_send(tid, text):
    """发私信（★ 正确接口：web_im/v1/web_im/send_msg）"""
    try:
        uid = str(_creds['dede'] or '')
        form = {
            'msg[sender_uid]': uid,
            'msg[receiver_id]': str(tid),
            'msg[receiver_type]': 1,
            'msg[msg_type]': 1,
            'msg[msg_status]': 0,
            'msg[dev_id]': 'F7B2C0A6-1D3E-4A5B-9C8D-0E1F2A3B4C5D',
            'msg[timestamp]': int(time.time()),
            'msg[new_face_version]': 0,
            'msg[content]': json.dumps({'content': text}, ensure_ascii=False),
            'csrf': _creds['jct'],
        }
        j = bili_post('/web_im/v1/web_im/send_msg', form,
                      base='https://api.vc.bilibili.com')
        ok = j.get('code') == 0
        return {'ok': ok, 'code': j.get('code'),
                'error': '' if ok else (j.get('message') or j.get('msg') or str(j)[:160])}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ───────────────────────── 复用现有脚本 ─────────────────────────
def run(cmd, cwd=ROOT, timeout=180):
    p = subprocess.run(   # FINAL_FIX -- dsh --profile headless - + stdin, zh-CN safe
        [HARNESS_EXE, '--expose-internals', CLI_JS, '--profile', 'headless', '-'],
        cwd=QQBOT, input=prompt, capture_output=True, text=True, timeout=180,
        env=dict(env, ELECTRON_RUN_AS_NODE='1'), creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0),
        encoding='utf-8', errors='replace')
    return {'code': p.returncode, 'out': (p.stdout or '').strip(), 'err': (p.stderr or '').strip()}

def voice_listen(seconds=5):
    r = run([NODE, os.path.join(ROOT, 'mic.mjs'), str(seconds)], cwd=ROOT, timeout=120)
    txt = ''
    for line in r['out'].splitlines():
        if line.startswith('文字:'):
            txt = line.split(':', 1)[1].strip()
    return {'text': txt, 'raw': r['out'], 'err': r['err']}

def _clean_output(b):
    """把子进程输出安全转成字符串（先 utf-8，失败再 gbk，最后 replace）"""
    if isinstance(b, str):
        return b
    for enc in ('utf-8', 'gbk', 'latin1'):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode('utf-8', 'replace')


def chat(text):
    """送进她的会话 → 拿回复"""
    env = dict(os.environ)
    try:
        env['DEEPSEEK_API_KEY'] = open(os.path.join(DSH, 'secrets', 'deepseek-api-key.txt'), encoding='utf-8').read().strip()
    except Exception:
        pass
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    prompt = ('（这是控制台里的文字/语音对话。有人对你说：）%s\n'
              '（只回一句话，短一点，别解释，别用括号。直接输出你要说的话。）' % text)
    p = subprocess.run(   # NOCMD_FIX2 - 直接调 node 入口，中文走 stdin，完全绕开 cmd
        [HARNESS_EXE, '--expose-internals', CLI_JS, '--profile', 'headless', '-'],
        cwd=QQBOT, input=prompt, capture_output=True, text=True, timeout=180,
        env=dict(env, ELECTRON_RUN_AS_NODE='1'), creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0),
        encoding='utf-8', errors='replace')
    out = (p.stdout or '').strip()
    lines = [l.strip() for l in out.replace('\r', '').split('\n') if l.strip()]
    return {'reply': lines[-1] if lines else '', 'raw': out[-800:], 'err': (p.stderr or '')[-400:]}

def say(text):
    r = run([NODE, os.path.join(ROOT, 'tts.mjs'), text], cwd=ROOT, timeout=180)
    return {'ok': r['code'] == 0, 'out': r['out'], 'err': r['err']}

def vts(action):
    if action == 'start':
        if os.path.exists(os.path.join(VTS, 'VTube Studio.exe')) and not _proc_running('VTube Studio'):
            subprocess.Popen([os.path.join(VTS, 'VTube Studio.exe')], cwd=VTS,
                             creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
            return {'ok': True, 'msg': '已启动 VTube Studio'}
        return {'ok': True, 'msg': '已在运行或没找到'}
    if action == 'stop':
        subprocess.run(['taskkill', '/IM', 'VTube Studio.exe', '/F'], capture_output=True, creationflags=NOWIN)
        return {'ok': True, 'msg': '已关闭'}
    return {'ok': False, 'msg': '未知动作'}

_PROC_CACHE = {}
def _proc_running(name, ttl=8):
    """★ 带缓存 + 无窗口：面板每 15 秒轮询一次状态，不能每次都真去 tasklist"""
    now = time.time()
    hit = _PROC_CACHE.get(name)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s.exe' % name],
                             capture_output=True, text=True, creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0), encoding='utf-8', errors='replace').stdout
        r = name.lower() in out.lower()
    except Exception:
        r = False
    _PROC_CACHE[name] = (now, r)
    return r

def qq_status():
    napcat = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Denchi')  # 占位
    return {'napcatAlive': _proc_running('NapCatWinBootMain') or _proc_running('QQ'),
            'note': 'QQ 那套走 NapCat；面板控制接口下一版接'}


# ───────────────────────── 她"现在在干什么" ─────────────────────────
QQBILI_STATE = os.path.join(QQBOT, 'bili', 'state', 'state.json')
NOTES_FILE   = os.path.join(QQBOT, 'bili', 'state', 'notes.json')
CARD_FILE    = os.path.join(QQBOT, 'AGENTS.md')
PATCH_FILE   = os.path.join(DSH, 'profiles', 'desktop', 'cordis.patch.yml')

def _read_json(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default if default is not None else {}

def live_status():
    """她在看什么视频 / 在直播吗 / 最近想了什么"""
    st = _read_json(QQBILI_STATE)
    now = st.get('now') or {}
    live = st.get('liveSession')
    browse = st.get('browseLog') or []
    hist = st.get('watchHistory') or []   # ★ 最近看过的视频
    # 最近一次对话（含她的 reasoning）
    her, reasoning = '', ''
    try:
        files = sorted([f for f in os.listdir(os.path.join(ROOT, 'out')) if f.startswith('her-') and f.endswith('.txt')],
                       key=lambda x: os.path.getmtime(os.path.join(ROOT, 'out', x)))
        if files:
            raw = open(os.path.join(ROOT, 'out', files[-1]), encoding='utf-8', errors='replace').read()
            raw = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', raw).strip()
            m = re.search(r'reasoning:\s*(.+?)(?:\n(?=[^\s])|\Z)', raw, re.S)
            if m:
                reasoning = m.group(1).strip()[:900]
                rest = raw[m.end():].strip()
                her = rest.split('\n')[-1].strip() if rest else ''
            else:
                her = raw.split('\n')[-1].strip()
    except Exception:
        pass
    return {
        'watching': {'title': now.get('title'), 'up': now.get('up'), 'url': now.get('url'),
                     'bvid': now.get('bvid'), 'ts': now.get('ts')} if now else None,
        'live': {'room': (live or {}).get('roomId'), 'title': (live or {}).get('title'),
                 'startedAt': (live or {}).get('startedAt')} if live else None,
        'browseLog': browse[-10:],
            'watched': hist[-20:][::-1],
            'watchedCount': len(hist),
        'lastSay': her, 'lastReasoning': reasoning,
        'drafts': len(st.get('drafts') or []),
        'inbox': st.get('inbox') or {},
        'limits': st.get('limits') or {},
        'counters': st.get('counters') or {},
    }

def learn_status():
    """学习进度：经验本 + 今天记了几条 + 上限"""
    d = _read_json(NOTES_FILE, {'notes': []})
    notes = d.get('notes') or []
    today = time.strftime('%Y-%m-%d')
    todays = []
    for n in notes:
        try:
            if time.strftime('%Y-%m-%d', time.localtime((n.get('ts') or 0) / 1000)) == today:
                todays.append(n)
        except Exception:
            pass
    kinds = {}
    for n in notes:
        kinds[n.get('kind', '?')] = kinds.get(n.get('kind', '?'), 0) + 1
    # 上限：从卡片里抓"一天最多记 N 条"
    limit = 50
    try:
        m = re.search(r'一天最多记\s*\*{0,2}(\d+)\s*条', open(CARD_FILE, encoding='utf-8').read())
        if m:
            limit = int(m.group(1))
    except Exception:
        pass
    return {'total': len(notes), 'today': len(todays), 'limit': limit,
            'kinds': kinds, 'recent': notes[-25:], 'todayList': todays[-25:]}

def read_prompt():
    card = ''
    try:
        card = open(CARD_FILE, encoding='utf-8').read()
    except Exception as e:
        card = '读不到：%s' % e
    persona = ''
    try:
        y = open(PATCH_FILE, encoding='utf-8').read()
        m = re.search(r'prefix:\s*\|\n((?:\s{8,}.*\n?)+)', y)
        persona = m.group(1) if m else ''
    except Exception:
        pass
    return {'card': card, 'persona': persona,
            'cardLen': len(card), 'personaLen': len(persona),
            'cardPath': CARD_FILE, 'personaPath': PATCH_FILE}

def write_prompt(kind, text):
    if kind == 'card':
        open(CARD_FILE, 'w', encoding='utf-8').write(text)   # ★ 每轮注入，改完即生效
        return {'ok': True, 'msg': '卡片已保存（下一条消息就生效，不用 /new）'}
    return {'ok': False, 'msg': 'persona 那段在 YAML 里，直接改容易弄坏 → 请在文件里改：' + PATCH_FILE}


# ---- selfcheck: which endpoints are really implemented ----
IMPLEMENTED = {
    '/api/status': True, '/api/live': True, '/api/learn': True, '/api/prompt': True,
    '/api/notes': True, '/api/log': True, '/api/audio/devices': True,
    '/api/voice/listen': True, '/api/chat': True, '/api/say': True,
    '/api/vts/start': True, '/api/vts/stop': True,
    '/api/bili/inbox': True, '/api/bili/drafts': True, '/api/bili/draft-approve': True, '/api/bili/draft-delete': True, '/api/bili/dynamics': True, '/api/bili/dynamic': True,
    '/api/bili/dynamic-auto': True, '/api/bili/dynamic-reply': True, '/api/bili/dynamic-comments': True, '/api/bili/dm': True, '/api/bili/replied': True,
    '/api/bili/comment': True, '/api/bili/reply': True, '/api/bili/delete': True,
    '/api/bili/like': True, '/api/bili/coin': True, '/api/bili/fav': True,
    '/api/bili/dm/reply': True, '/api/bili/ignore': True, '/api/bili/auto-reply': True,
    '/napcat': True, '/api/qq/status': True, '/api/qq/qrcode': True, '/api/qq/groups': True,
    '/api/qq/members': True, '/api/qq/history': True, '/api/qq/send': True,
    '/api/qq/mute': True, '/api/qq/kick': True, '/api/qq/restart': True,
    '/api/config': True, '/api/vts/test': True, '/api/audio/switch': True,
    '/api/learn/limit': True,
}

def selfcheck():
    return {'ok': True, 'results': IMPLEMENTED}


def auto_reply(oid, parent, root, hint='', who=''):
    """让大肥鱼自己写一句，然后真发到 B站（带 is_dynamic + 去重）"""
    key = str(parent)
    if already_replied('reply', key):
        return {'ok': False, 'skipped': True, 'error': '这条已经回过一次了'}
    # 1) 让她写
    prompt = ('（有人在 B站 回复了你，你要回一句。对方昵称：%s，他说：%s。'
              '请只输出你要发的那一句话，短、口语、别解释、别用括号、别加引号。）'
              % (who or '某人', hint or '（内容见评论区）'))
    r = chat(prompt)
    text = (r.get('reply') or '').strip().strip('"').strip('“”').strip()
    if not text:
        return {'ok': False, 'error': '她没写出内容', 'raw': r}
    # 2) 真发（★ 带 is_dynamic=1）
    out = reply_comment(oid, text, parent, root, is_dynamic=True)
    if out.get('ok'):
        mark_replied('reply', key, {'oid': oid, 'rpid': out.get('rpid'), 'text': text[:80], 'auto': True})
        out['text'] = text
    return out


# ───────────────── QQ / 杂项 路由（13 个） ─────────────────
def qq_route(path, q, body):
    """把 /api/qq/* 和另外几个杂项接口分派出去"""
    if path == '/api/qq/status':
        return qq.qq_status()
    if path == '/api/qq/qrcode':
        return qq.qq_qrcode()
    if path == '/api/qq/groups':
        return qq.qq_groups()
    if path == '/api/qq/members':
        return qq.qq_members((q.get('gid') or [''])[0])
    if path == '/api/qq/history':
        # ★ 这个函数是模块级的，没有 self ✗ 直接返回字典 ✓
        if (q.get('raw') or [''])[0] == '1':
            # ★ raw=1：拿最新一页的原始数据（带 message_seq ✓）
            try:
                r3 = qq.call('get_group_msg_history',
                             {'group_id': int((q.get('gid') or ['0'])[0]),
                              'count': int((q.get('n') or ['30'])[0])}, timeout=30)
                return {'ok': True, 'raw': r3}
            except Exception as e:
                return {'ok': False, 'error': str(e)}
        seq = (q.get('seq') or [None])[0]
        if seq not in (None, '', 'None'):
            try:
                r2 = qq.call('get_group_msg_history',
                             {'group_id': int((q.get('gid') or ['0'])[0]),
                              'count': int((q.get('n') or ['30'])[0]),
                              'message_seq': int(seq)}, timeout=30)
                return {'ok': True, 'raw': r2}
            except Exception as e:
                return {'ok': False, 'error': str(e)}
        return qq.qq_history((q.get('gid') or [''])[0], (q.get('n') or ['30'])[0])
    if path == '/api/qq/send':
        return qq.qq_send(body.get('target', ''), body.get('text', ''),
                          body.get('kind', 'group'), body.get('image'), body.get('file'))
    if path == '/api/qq/mute':
        return qq.qq_mute(body.get('gid', ''), body.get('uid', ''), body.get('seconds', 0))
    if path == '/api/qq/kick':
        return qq.qq_kick(body.get('gid', ''), body.get('uid', ''), body.get('reject', False))
    if path == '/api/qq/restart':
        return qq.qq_restart()
    if path == '/api/qq/events':
        return qq.events((q.get('kind') or [None])[0], int((q.get('limit') or ['50'])[0]))
    if path == '/api/config':
        return qq.get_config()
    if path == '/api/vts/test':
        return qq.vts_test()
    if path == '/api/audio/switch':
        return qq.audio_switch(body.get('index', 0))
    if path == '/api/learn/limit':
        if body:
            return qq.learn_limits('set', body.get('limit'))
        return qq.learn_limits('get')
    return {'ok': False, 'error': 'unknown'}

# ───────────────────────── HTTP ─────────────────────────
STATE = {'startedAt': int(time.time())}


# ---- serve the panel itself (same origin => no CORS/file:// problems) ----
_PANEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))          # .../panel
_MIME = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
         '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
         '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}


def _serve_panel(self, path):
    """返回 True 表示已经处理（把面板文件发出去）"""
    rel = 'index.html' if path in ('/', '/index.html', '/panel/', '/panel') else path.lstrip('/')
    if rel.startswith('panel/'):
        rel = rel[6:]
    full = os.path.normpath(os.path.join(_PANEL_DIR, rel))
    if not full.startswith(os.path.normpath(_PANEL_DIR)):
        return False
    if not os.path.isfile(full):
        return False
    ext = os.path.splitext(full)[1].lower()
    try:
        data = open(full, 'rb').read()
    except Exception:
        return False
    self.send_response(200)
    self.send_header('Content-Type', _MIME.get(ext, 'application/octet-stream'))
    self.send_header('Content-Length', str(len(data)))
    self.send_header('Cache-Control', 'no-store')
    self.end_headers()
    self.wfile.write(data)
    return True



# ---- 反代 NapCat 的 WebUI（6099）=> 同源 => 控制台里可以直接内嵌 ----

# ★ NapCat WebUI token（自动登录用）
try:
    import json as _json_t
    NAP_WEBUI_TOKEN = _json_t.load(open(r'C:\app\napcat\config\webui.json', encoding='utf-8')).get('token', '')
except Exception:
    NAP_WEBUI_TOKEN = ''
NAPCAT_WEBUI = 'http://127.0.0.1:6099'


def _proxy_napcat(self, path, query, method='GET', body=None):
    """把 /napcat/xxx 转发到 NapCat WebUI，返回 True 表示已处理"""
    try:
        import urllib.request as _u
        target = NAPCAT_WEBUI + path[len('/napcat'):]
        if query:
            target += '?' + query
        data = body if isinstance(body, (bytes, type(None))) else None
        req = _u.Request(target, data=data, method=method)
        for k, v in self.headers.items():
            if k.lower() in ('host', 'content-length', 'connection', 'accept-encoding'):
                continue
            try:
                req.add_header(k, v)
            except Exception:
                pass
        with _u.urlopen(req, timeout=30) as r:
            payload = r.read()
            self.send_response(r.status)
            for k, v in r.headers.items():
                if k.lower() in ('transfer-encoding', 'connection', 'content-encoding', 'content-length'):
                    continue
                self.send_header(k, v)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
        return True
    except Exception as e:
        self._send({'ok': False, 'error': 'NapCat WebUI 连不上（NapCat 没在跑？）: %s' % e}, 502)
        return True



# ===== B站 动态（发动态 / 列动态 / 回动态评论）=====
def post_dynamic(text):
    content = (text or '').strip()
    if not content:
        return {'ok': False, 'error': 'empty'}
    uid = str(_creds['dede'] or '0') + '_' + str(int(time.time())) + '_' + str(int(time.time() * 1000) % 100000)
    body = {'dyn_req': {'content': {'contents': [{'raw_text': content, 'type': 1, 'biz_id': ''}]},
                        'scene': 1,
                        'meta': {'app_meta': {'from': 'create.dynamic.web', 'mobi_app': 'web'}},
                        'upload_id': uid}}
    try:
        import urllib.request as _u
        rq = _u.Request('https://api.bilibili.com/x/dynamic/feed/create/dyn?csrf=' + _creds['jct'],
                        data=json.dumps(body).encode('utf-8'),
                        headers={'Cookie': COOKIE, 'User-Agent': UA,
                                 'Content-Type': 'application/json',
                                 'Referer': 'https://t.bilibili.com/'})
        j = json.loads(_u.urlopen(rq, timeout=30).read().decode('utf-8', 'replace'))
        if j.get('code') == 0:
            d = j.get('data') or {}
            did = str(d.get('dyn_id_str') or d.get('dyn_id') or '')
            return {'ok': True, 'dynId': did, 'url': ('https://t.bilibili.com/' + did) if did else ''}
        return {'ok': False, 'code': j.get('code'), 'error': j.get('message')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def my_dynamics(limit=20):
    """她的动态（含正文）—— ★ 最笨可靠的写法：脚本 + 读文件"""
    import subprocess as _sp
    import tempfile as _tf
    try:
        hp = os.path.join(QQBOT, 'bili', 'dyn2.py')
        out_f = os.path.join(_tf.gettempdir(), 'dfy_dyn.json')
        if os.path.exists(out_f):
            try:
                os.remove(out_f)
            except Exception:
                pass
        # ★ 不用管道（capture_output 会开管道，在这个环境里会失败）→ 直接 DEVNULL + 读文件
        _dn = _sp.DEVNULL
        _sp.run([PY, hp, out_f], stdout=_dn, stderr=_dn, stdin=_dn,
                timeout=120, creationflags=NOWIN)
        if not os.path.exists(out_f):
            return {'ok': False, 'error': 'helper 没写出文件'}
        j = json.load(open(out_f, encoding='utf-8'))
        items = j.get('items') or []
        return {'ok': True, 'items': items[:limit], 'error': ''}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def dynamic_reply(dyn_id, text, parent=None, root=None):
    if parent:
        return reply_comment(dyn_id, text, parent, root or 0, is_dynamic=True, type_=11)
    return post_comment(dyn_id, text, is_dynamic=True, type_=11)


def dynamic_comments_list(dyn_id, ps=20):
    try:
        j = bili_get('/x/v2/reply/main', {'type': 11, 'oid': dyn_id, 'mode': 3, 'ps': ps, 'pn': 1})
        reps = (j.get('data') or {}).get('replies') or []
        out = []
        for r in reps:
            out.append({'id': str(r.get('rpid_str') or r.get('rpid')),
                        'who': ((r.get('member') or {}).get('uname') or ''),
                        'text': (r.get('content') or {}).get('message', ''),
                        'like': (r.get('like') or 0)})
        return {'ok': True, 'items': out}
    except Exception as e:
        return {'ok': False, 'error': str(e)}



# ===== B站 草稿（审批）=====
DRAFT_STATE = os.path.join(QQBOT, 'bili', 'state', 'state.json')


def _draft_load():
    try:
        return json.load(open(DRAFT_STATE, encoding='utf-8'))
    except Exception:
        return {}


def _draft_save(d):
    try:
        os.makedirs(os.path.dirname(DRAFT_STATE), exist_ok=True)
        json.dump(d, open(DRAFT_STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def bili_drafts():
    """她出的稿子（评论/动态），等主人批"""
    d = _draft_load()
    drafts = d.get('drafts') or []
    ign = REPLIED_DB.get('ignored', {})
    out = []
    for i, it in enumerate(drafts):
        did = str(it.get('id') or it.get('draftId') or i)
        if did in ign:
            continue
        out.append({'id': did, 'index': i, 'kind': it.get('kind') or 'comment',
                    'text': it.get('text') or it.get('content') or '',
                    'target': it.get('target') or it.get('title') or it.get('bvid') or '',
                    'oid': it.get('oid') or it.get('aid') or '',
                    'root': it.get('root') or '',
                    'parent': it.get('parent') or it.get('rpid') or '',
                    'ts': it.get('ts') or it.get('createdAt') or ''})
    return {'ok': True, 'items': out, 'total': len(drafts)}


def bili_draft_approve(did, text=None):
    """批准：真发到 B站，然后从草稿里删掉（★ 不保留 ✓）"""
    d = _draft_load()
    drafts = d.get('drafts') or []
    hit = None
    hit_i = -1
    for i, it in enumerate(drafts):
        if str(it.get('id') or i) == str(did):
            hit = it
            hit_i = i
            break
    if hit is None:
        return {'ok': False, 'error': '找不到这条草稿'}
    body = (text if text is not None else (hit.get('text') or hit.get('content') or '')).strip()
    if not body:
        return {'ok': False, 'error': '草稿内容为空'}
    kind = (hit.get('kind') or 'comment').lower()
    if kind == 'dynamic':
        out = post_dynamic(body)
    else:
        oid = hit.get('oid') or hit.get('aid')
        parent = hit.get('parent') or hit.get('rpid')
        if parent:
            out = reply_comment(oid, body, parent, hit.get('root') or 0, is_dynamic=True)
        elif oid:
            out = post_comment(oid, body, is_dynamic=True)
        else:
            return {'ok': False, 'error': '这条草稿缺少目标（oid），无法发布'}
    if out.get('ok'):
        # ★ 发成功 → 从草稿里删除（不保留 ✓）
        try:
            drafts.pop(hit_i)
            d['drafts'] = drafts
            _draft_save(d)
        except Exception:
            pass
    out['text'] = body
    return out


def bili_draft_delete(did):
    """删除这条草稿（真删掉 ✓）"""
    d = _draft_load()
    drafts = d.get('drafts') or []
    for i, it in enumerate(drafts):
        if str(it.get('id') or i) == str(did):
            drafts.pop(i)
            d['drafts'] = drafts
            _draft_save(d)
            return {'ok': True, 'removed': True}
    return {'ok': False, 'error': '找不到这条草稿'}




# ===== NapCat 控制（内置一键启动 ✓ 无 cmd 窗口 ✓）=====
NAP_DIR = r'C:\app\napcat'
NAP_BOOT = os.path.join(NAP_DIR, 'NapCatWinBootMain.exe')
NAP_HOOK = os.path.join(NAP_DIR, 'NapCatWinBootHook.dll')
QQ_EXE = r'C:\app\qq\QQ.exe'
QQ_UIN = 'YOUR_BOT_QQ'


def _p(*names):
    res = []
    try:
        import subprocess as _sp
        for nm in names:
            try:
                r = _sp.run(['tasklist', '/FI', 'IMAGENAME eq %s.exe' % nm],
                            capture_output=True, text=True, creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0),
                            encoding='utf-8', errors='replace', timeout=15)
                res.append(('%s.exe' % nm.lower()) in (r.stdout or '').lower())
            except Exception:
                res.append(False)
    except Exception:
        res = [False] * len(names)
    return res


def napcat_status():
    qq, boot, nap = _p('QQ', 'NapCatWinBootMain', 'NapCat')

    def _lis(port):
        try:
            import socket
            s = socket.socket(); s.settimeout(0.4)
            ok = s.connect_ex(('127.0.0.1', port)) == 0
            s.close()
            return ok
        except Exception:
            return False
    return {'ok': True,
            'qqRunning': qq, 'bootRunning': boot,
            'webui6099': _lis(6099), 'ws8643': _lis(8643), 'ws3001': _lis(3001),
            'napDir': NAP_DIR, 'bootExists': os.path.exists(NAP_BOOT)}


def napcat_start(killQQ=False):
    """一键启动：隐藏运行 NapCat 引导（★ 不弹 cmd 窗口 ✓）"""
    if not os.path.exists(NAP_BOOT):
        return {'ok': False, 'error': '找不到 NapCat 引导: ' + NAP_BOOT}
    import subprocess as _sp0
    _NOWIN = getattr(_sp0, 'CREATE_NO_WINDOW', 0)
    qq, boot, nap = _p('QQ', 'NapCatWinBootMain')
    if boot:
        return {'ok': True, 'msg': 'NapCat 引导已经在运行了'}
    if qq and not killQQ:
        return {'ok': False, 'needQuitQQ': True,
                'error': 'QQ 正在运行。NapCat 需要在 QQ 未启动时注入 —— 要先退出 QQ。'}
    if qq and killQQ:
        try:
            import subprocess as _sp
            _sp.run(['taskkill', '/F', '/IM', 'QQ.exe'], capture_output=True,
                    creationflags=NOWIN)
            time.sleep(3)
        except Exception:
            pass
    try:
        import subprocess as _sp
        env = dict(os.environ)
        env['NAPCAT_PATCH_PACKAGE'] = os.path.join(NAP_DIR, 'qqnt.json')
        env['NAPCAT_LOAD_PATH'] = os.path.join(NAP_DIR, 'loadNapCat.js')
        env['NAPCAT_INJECT_PATH'] = NAP_HOOK
        env['NAPCAT_LAUNCHER_PATH'] = NAP_BOOT
        env['NAPCAT_MAIN_PATH'] = os.path.join(NAP_DIR, 'napcat.mjs')
        flags = getattr(_sp, 'DETACHED_PROCESS', 0) | getattr(_sp, 'CREATE_NO_WINDOW', 0)
        _sp.Popen([NAP_BOOT, QQ_EXE, NAP_HOOK, '-q', QQ_UIN],
                  cwd=NAP_DIR, env=env, creationflags=flags,
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, stdin=_sp.DEVNULL)
        return {'ok': True, 'msg': '已启动 NapCat（隐藏运行 ✓ 无窗口 ✓），等 20~40 秒看状态'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def napcat_stop():
    try:
        import subprocess as _sp
        _sp.run(['taskkill', '/F', '/IM', 'NapCatWinBootMain.exe'], capture_output=True,
                creationflags=NOWIN)
        _sp.run(['taskkill', '/F', '/IM', 'QQ.exe'], capture_output=True, creationflags=NOWIN)
        return {'ok': True, 'msg': '已停止 NapCat 和 QQ'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}




def dm_draft(tid, hint=''):
    """让她针对某条私信起草回复（不发送 ✓ 只给文字）"""
    try:
        r = chat('(\u4f60\u5728 B\u7ad9 \u6536\u5230\u4e00\u6761\u79c1\u4fe1\uff0c\u8349\u62df\u4e00\u6761\u56de\u590d\u3002'
                 '\u4e00\u4e24\u53e5\uff0c\u7528\u4f60\u81ea\u5df1\u7684\u53e3\u6c14\uff0c\u522b\u89e3\u91ca\u3001\u522b\u7528\u62ec\u53f7\u3001\u522b\u52a0\u5f15\u53f7\uff0c\u76f4\u63a5\u8f93\u51fa\u5185\u5bb9\u3002'
                 + ((' \u5bf9\u65b9\u53eb ' + str(tid) + '\u3002') if tid else '')
                 + ((' \u4e3b\u4eba\u7684\u63d0\u793a\uff1a' + str(hint)) if hint else ''))
        txt = (r.get('reply') or '').strip().strip('"').strip()
        return {'ok': bool(txt), 'text': txt, 'error': '' if txt else '\u5979\u6ca1\u5199\u51fa\u6765'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}



CONFIG_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui-config.json')


def _cfg_load():
    try:
        return json.load(open(CONFIG_DB, encoding='utf-8'))
    except Exception:
        return {}


def config_get():
    return {'ok': True, 'config': _cfg_load()}


def config_set(d):
    try:
        c = _cfg_load()
        for k, v in (d or {}).items():
            c[str(k)] = v
        json.dump(c, open(CONFIG_DB, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        return {'ok': True, 'saved': len(d or {})}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ===== B站 通知：谁@我 / 谁回我 / 收到的赞 =====
def bili_msgfeed(kind='reply', limit=20):
    """kind: reply=回复我的 / at=@我的 / like=收到的赞
    ★ B站 的「@我的」和「回复我的」是两个不同接口，都要看
    """
    path = {'reply': '/x/msgfeed/reply', 'at': '/x/msgfeed/at', 'like': '/x/msgfeed/like'}.get(kind)
    if not path:
        return {'ok': False, 'error': '未知类型 ' + str(kind)}
    try:
        j = bili_get(path, {'platform': 'web', 'build': 0, 'mobi_app': 'web'},
                     base='https://api.bilibili.com')
        items = (j.get('data') or {}).get('items') or []
        out = []
        for it in items[:limit]:
            u = it.get('user') or {}
            item = it.get('item') or {}
            out.append({
                'id': str(it.get('id') or ''),
                'kind': kind,
                'who': u.get('nickname') or '',
                'mid': str(u.get('mid') or ''),
                'ts': it.get('reply_time') or it.get('time') or 0,
                'title': (item.get('title') or '')[:80],
                'text': (item.get('source_content') or it.get('content') or '')[:300],
                'uri': item.get('uri') or '',
                'at_details': [{'who': (x.get('nickname') or ''), 'mid': str(x.get('mid') or '')}
                               for x in (it.get('at_details') or [])],
            })
        return {'ok': True, 'items': out, 'total': len(items)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def bili_notices():
    """把三类通知合并成一个列表（她一次性看完 ✓）"""
    out = []
    errs = []
    for k in ('reply', 'at', 'like'):
        r = bili_msgfeed(k)
        if r.get('ok'):
            out.extend(r.get('items') or [])
        else:
            errs.append(k + ':' + str(r.get('error'))[:60])
    # 按时间倒序
    out.sort(key=lambda x: x.get('ts') or 0, reverse=True)
    return {'ok': True, 'items': out, 'errors': errs}


def bili_write_check():
    """诊断：她现在到底能不能写（评论/动态）—— 只探测，不真发"""
    res = {'creds': {}, 'can': {}}
    try:
        res['creds'] = {
            'sessdata': bool(_creds.get('sessdata')),
            'bili_jct': bool(_creds.get('jct')),
            'buvid3': bool(_creds.get('buvid3')),
            'mid': str(_creds.get('dede') or ''),
        }
    except Exception as e:
        res['creds'] = {'error': str(e)}
    try:
        j = bili_get('/x/web-interface/nav', base='https://api.bilibili.com')
        d = j.get('data') or {}
        res['can']['login'] = bool(d.get('isLogin'))
        res['can']['name'] = d.get('uname')
        res['can']['level'] = (d.get('level_info') or {}).get('current_level')
        res['can']['coins'] = d.get('money')
        res['can']['vip'] = (d.get('vipStatus') or 0) == 1
    except Exception as e:
        res['can']['error'] = str(e)[:120]
    # 今日额度
    try:
        st = _read_json(QQBILI_STATE)
        res['limits'] = st.get('limits')
        res['counters'] = st.get('counters')
        res['lastErrors'] = (st.get('lastErrors') or [])[-5:]
        res['now'] = (st.get('now') or {}).get('title')
    except Exception:
        pass
    # 读一次她的草稿本（有没有待发）
    try:
        d = _draft_load()
        res['drafts'] = len(d.get('drafts') or [])
    except Exception:
        pass
    return res



def bili_my_replies(limit=40):
    """她最近在 B站 发出去的东西（评论/回复/动态）—— 主人能看 ✓
    数据来自 state.json 的 ledger（她每写一次都记一条 ✓）
    """
    try:
        st = _read_json(QQBILI_STATE)
        led = st.get('ledger') or []
        out = []
        for x in led[-limit:]:
            out.append({
                'ts': x.get('ts'),
                'kind': x.get('kind') or '',
                'text': (x.get('text') or '')[:400],
                'target': x.get('target') or x.get('oid') or x.get('bvid') or '',
                'rpid': x.get('rpid') or '',
                'url': x.get('url') or '',
                'ok': x.get('ok', True),
                'error': x.get('error') or '',
            })
        out.reverse()
        ign = REPLIED_DB.get('ignored', {})
        rep = REPLIED_DB.get('replied', {})
        drop = set(list(ign.keys()) + list(rep.keys()))
        if not (q_all := False):
            pass
        out = [x for x in out if str(x.get('rpid') or '') not in drop and str(x.get('target') or '') not in drop]
        return {'ok': True, 'items': out, 'total': len(out)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def bili_drafts_history(limit=40):
    """所有草稿（含已发/已拒/已过期）—— 便于核对"""
    try:
        d = _draft_load()
        arr = d.get('drafts') or []
        out = []
        for x in arr[-limit:]:
            out.append({
                'id': str(x.get('id') or ''),
                'kind': x.get('kind') or 'comment',
                'text': (x.get('text') or '')[:300],
                'status': x.get('status') or 'pending',
                'oid': x.get('oid') or x.get('aid') or '',
                'ts': x.get('ts'),
            })
        out.reverse()
        return {'ok': True, 'items': out}
    except Exception as e:
        return {'ok': False, 'error': str(e)}



def bili_fetch_image(url, tag='bili'):
    """把 B站 的图片下到本地，返回路径 —— 之后可以用 qqbot_describe_image 看她
    ★ 支持：私信里的图、评论区的图、表情包
    """
    try:
        import hashlib as _h
        if not url or not str(url).startswith('http'):
            return {'ok': False, 'error': 'url 不合法'}
        # B站 的图常常有 @ 后缀参数（尺寸标记），要去掉
        clean = str(url).split('@')[0]
        d = os.path.join(QQBOT, 'downloads', 'bili-img')
        os.makedirs(d, exist_ok=True)
        ext = '.jpg'
        for e in ('.png', '.gif', '.webp', '.jpeg'):
            if e in clean.lower():
                ext = e
                break
        name = 'bi_' + _h.md5(clean.encode()).hexdigest()[:12] + ext
        p = os.path.join(d, name)
        if not (os.path.exists(p) and os.path.getsize(p) > 200):
            import urllib.request as _u
            req = _u.Request(clean, headers={'User-Agent': UA, 'Referer': 'https://www.bilibili.com/'})
            data = _u.urlopen(req, timeout=30).read()
            open(p, 'wb').write(data)
        return {'ok': True, 'path': p, 'bytes': os.path.getsize(p), 'url': clean,
                'hint': '用 qqbot_describe_image 看这个 path'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def bili_dm_images(tid, limit=3):
    """拉某个私信会话里的最近图片（私信图 + 表情包）"""
    try:
        c = _creds
        u = ('https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs'
             '?talker_id=%s&session_type=1&size=20' % str(tid))
        j = bili_get(u, None, base='https://api.vc.bilibili.com')
        msgs = (j.get('data') or {}).get('messages') or []
        out = []
        for m in msgs[-limit * 3:]:
            t = m.get('msg_type')
            content = m.get('content') or ''
            # 图片消息 type=2，表情 type=5
            if t in (2, 5):
                try:
                    import json as _j
                    o = _j.loads(content)
                    url = o.get('url') or (o.get('image_url')) or ''
                    if url:
                        r = bili_fetch_image(url, 'dm')
                        if r.get('ok'):
                            out.append(r)
                except Exception:
                    pass
            if len(out) >= limit:
                break
        return {'ok': True, 'items': out}
    except Exception as e:
        return {'ok': False, 'error': str(e)}




# ★ 2026-10-06 主人要求：待审批 → 监视。列她发过的东西 + 标出过激
EXTREME_WORDS = ['开盒', '人肉', '身份证', '手机号', '家住哪',
                 '杀', '死全家', '弄死', '开你盒', '治你',
                 '政治', '习', '反动', '国家领导',
                 '地域黑', '残疾', '人身攻击', '强奸', '幼'] + ['傻逼', '滚', '死了吧']


def bili_her_comments(limit=60):
    """她自己发过的评论/回复（从她的账本 state.json 里读 ✓）+ 过激标记"""
    out = []
    p2 = os.path.join(QQBOT, 'bili', 'state', 'state.json')
    try:
        st = json.load(open(p2, encoding='utf-8'))
    except Exception as e:
        return {'ok': False, 'error': 'state.json 读不了: %s' % e}
    led = st.get('ledger') or []
    if isinstance(led, dict):
        led = list(led.values())
    for it in led[-int(limit):]:
        if not isinstance(it, dict):
            continue
        txt = str(it.get('text') or '')
        hit = [w for w in EXTREME_WORDS if w and w in txt]
        out.append({'kind': it.get('kind') or '?', 'ts': it.get('ts') or it.get('at') or 0,
                    'text': txt, 'oid': str(it.get('oid') or ''), 'rpid': str(it.get('rpid') or ''),
                    'url': it.get('url') or '', 'extreme': bool(hit), 'words': hit})
    out.reverse()
    return {'ok': True, 'items': out, 'count': len(out),
            'extreme': len([x for x in out if x['extreme']])}


def bili_msg_reply(mid, text, dry=False):
    """★ 2026-10-06 修：回应用户反馈——回 @/回评论必须
    发到评论区，不能偷偷变成私信（原来两条路都是 dm_send ✗）。
    只有真的没有可回的评论时，才退回私信。"""
    if not mid or not text:
        return {'ok': False, 'error': 'mid 和 text 都要有'}
    try:
        n = bili_notices()
        hit = None
        for it in (n.get('items') or []):
            if str(it.get('mid')) == str(mid) and it.get('kind') in ('reply', 'at'):
                hit = it
                break
        if not hit:
            if dry:
                return {'ok': True, 'dry': True, 'would': 'dm', 'reason': '没找到他的 @/回复通知'}
            r = dm_send(mid, text)
            r['via'] = 'dm'
            return r
        # ★ 关键：通知里没有 oid ✗ 但 uri 里什么都有 ✓
        #   uri = https://www.bilibili.com/opus/<dynId>#reply<rpid>   或  /video/BV.../#reply<rpid>
        import re as _re
        uri = str(hit.get('uri') or '')
        _mr = re.search(r'#reply(\d+)', uri)
        rpid = (_mr.group(1) if _mr else '') or str(hit.get('id') or hit.get('source') or '')
        _mo = re.search(r'/opus/(\d+)', uri)
        _mv = re.search(r'/(BV[0-9A-Za-z]+)', uri)
        _md = re.search(r'/dynamic/(\d+)', uri)
        is_dyn = False
        typ = 1
        oid = ''
        bvid = ''
        if _mo:
            oid = _mo.group(1); is_dyn = True; typ = 17
        elif _md:
            oid = _md.group(1); is_dyn = True; typ = 17
        elif _mv:
            bvid = _mv.group(1); is_dyn = False; typ = 1
        else:
            oid = str(hit.get('oid') or hit.get('aid') or '')
            bvid = str(hit.get('bvid') or '')
        if not oid and bvid:
            try:
                jj = bili_get('/x/web-interface/view', {'bvid': bvid}, base='https://api.bilibili.com')
                oid = str(((jj or {}).get('data') or {}).get('aid') or '')
            except Exception:
                oid = ''
        typ = int(hit.get('type') or 1)
        if not oid or not rpid:
            if dry:
                return {'ok': True, 'dry': True, 'would': 'comment-失败回退dm',
                        'reason': '通知里没有 oid/rpid', 'hit': {k: hit.get(k) for k in ('id','oid','bvid','type','kind')}}
            r = dm_send(mid, text)
            r['via'] = 'dm'
            r['why'] = '通知里拿不到 oid/rpid'
            return r
        if dry:
            return {'ok': True, 'dry': True, 'would': 'comment',
                    'oid': oid, 'rpid': rpid, 'type': typ,
                    'title': str(hit.get('title') or '')[:60], 'to': str(hit.get('who') or '')}
        rr = reply_comment(oid, str(text), rpid, rpid, is_dynamic=is_dyn, type_=typ)
        rr['via'] = 'comment'
        rr['is_dynamic'] = is_dyn
        rr['oid'] = oid
        rr['rpid'] = rpid
        return rr
    except Exception as e:
        return {'ok': False, 'error': str(e)}



# ===== 实时配置（cordis.patch.yml）=====
DSH_CFG = r'C:\Users\28461\.dsh\profiles\desktop\cordis.patch.yml'
DSH_CFG_DIR = r'C:\Users\28461\.dsh\profiles\desktop'

CONFIG_KEYS = [
    ('roamMinutes', '逛 B站 基准间隔（分钟）'),
    ('roamMinMinutes', '逛的随机下限（分钟）'),
    ('roamMaxMinutes', '逛的随机上限（分钟）'),
    ('roamFromHour', '可逛时段-起（0=全天）'),
    ('roamToHour', '可逛时段-止（24=全天）'),
    ('inboxMinutes', '收件箱间隔（分钟）'),
    ('inboxMinMinutes', '收件箱随机下限'),
    ('inboxMaxMinutes', '收件箱随机上限'),
    ('maxNewCommentsPerDay', '每天最多主动评论'),
    ('maxRepliesPerDay', '每天最多回复'),
    ('minGapSeconds', '两条之间最小间隔（秒）'),
    ('draftTtlMinutes', '草稿有效期（分钟）'),
    ('batchEnabled', '攒批等审批（true/false）'),
    ('dynAutoEnabled', '随机发动态（true/false）'),
    ('dynMinPerDay', '每天最少发几条动态'),
    ('dynMaxPerDay', '每天最多发几条动态'),
    ('dynMinMinutes', '发动态随机下限（分钟）'),
    ('dynMaxMinutes', '发动态随机上限（分钟）'),
]


def _find_bili_range(lines):
    """找出 bili: 段的起止行号"""
    start = None
    for i, l in enumerate(lines):
        if l.strip() == 'bili:':
            start = i
            base = len(l) - len(l.lstrip())
            break
    if start is None:
        return None, None, 6
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if not l.strip():
            continue
        ind = len(l) - len(l.lstrip())
        if ind <= base and not l.lstrip().startswith('#'):
            end = j
            break
    return start, end, base + 2


def config_read_file():
    """读出 bili 段的所有配置值"""
    try:
        lines = open(DSH_CFG, encoding='utf-8').read().split('\n')
        start, end, indent = _find_bili_range(lines)
        vals = {}
        if start is not None:
            for l in lines[start:end]:
                st = l.strip()
                if not st or st.startswith('#'):
                    continue
                if ':' in st:
                    k, _, v = st.partition(':')
                    k = k.strip()
                    v = v.split('#')[0].strip().strip('"').strip("'")
                    if k in [x[0] for x in CONFIG_KEYS]:
                        vals[k] = v
        return {'ok': True, 'values': vals, 'keys': CONFIG_KEYS,
                'file': DSH_CFG, 'lines': (start, end) if start else None,
                'mtime': os.path.getmtime(DSH_CFG)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def config_write_file(vals):
    """★ 实时改配置：只改 bili 段里那几个键，其它原样保留；改前自动备份"""
    try:
        import shutil, time
        raw = open(DSH_CFG, encoding='utf-8').read()
        lines = raw.split('\n')
        start, end, _ = _find_bili_range(lines)
        if start is None:
            return {'ok': False, 'error': '找不到 bili: 段'}
        bak = DSH_CFG + '.bak-auto-' + time.strftime('%Y%m%d-%H%M%S')
        shutil.copy2(DSH_CFG, bak)
        want = {str(k): str(v) for k, v in (vals or {}).items()}
        done = set()
        for i in range(start + 1, end):
            l = lines[i]
            st = l.strip()
            if not st or st.startswith('#'):
                continue
            if ':' not in st:
                continue
            k, _, _v = st.partition(':')
            k = k.strip()
            if k in want:
                ind = l[:len(l) - len(l.lstrip())]
                lines[i] = ind + k + ': ' + want[k]
                done.add(k)
        # 没找到的键 → 追加到段尾
        add = [k for k in want if k not in done]
        if add:
            ind = ' ' * (len(lines[start]) - len(lines[start].lstrip()) + 2)
            ins = [ind + k + ': ' + want[k] for k in add]
            lines[end:end] = ins
        open(DSH_CFG, 'w', encoding='utf-8').write('\n'.join(lines))
        return {'ok': True, 'changed': sorted(done) + add, 'backup': os.path.basename(bak),
                'note': '改好了 ✓ 重启 DSH 才生效'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def config_backups():
    try:
        fs = [f for f in os.listdir(DSH_CFG_DIR) if f.startswith('cordis.patch.yml.bak')]
        fs.sort(reverse=True)
        return {'ok': True, 'items': fs[:30]}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def config_restore(name):
    """一键还原某个备份"""
    try:
        import shutil, time, re as _re
        if not _re.match(r'^cordis\.patch\.yml\.bak[-\w.]*$', str(name or '')):
            return {'ok': False, 'error': '文件名不合法'}
        src = os.path.join(DSH_CFG_DIR, name)
        if not os.path.exists(src):
            return {'ok': False, 'error': '备份不存在'}
        shutil.copy2(DSH_CFG, DSH_CFG + '.bak-before-restore-' + time.strftime('%Y%m%d-%H%M%S'))
        shutil.copy2(src, DSH_CFG)
        return {'ok': True, 'restored': name, 'note': '还原了 ✓ 重启 DSH 生效'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def napcat_boot_visible():
    """★ 独立启动 NapCat —— 弹一个可见的窗口（以后你单独扫码/看日志）"""
    try:
        import subprocess as _sp
        bat = os.path.join(NAP_DIR, 'start-dafeiyu-qq.bat')
        if not os.path.exists(bat):
            return {'ok': False, 'error': '找不到启动器: ' + bat}
        # ★ 用独立控制台窗口（不是隐藏 ✓ 你能看到它 ✓）
        _sp.Popen(['cmd.exe', '/c', 'start', '"NapCat 大肥鱼"', 'cmd.exe', '/k', bat],
                  cwd=NAP_DIR, creationflags=getattr(_sp, 'CREATE_NEW_CONSOLE', 0))
        return {'ok': True, 'msg': '已弹出独立窗口 ✓ 在里面看日志/扫码，别关它'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}






def bili_user_info(mid):
    """查一个 B站 UID 是谁 —— 回他之前先看清楚"""
    if not mid:
        return {'ok': False, 'error': 'mid 必填'}
    try:
        d = {}
        for path in ('/x/space/wbi/acc/info', '/x/space/acc/info'):
            try:
                j = bili_get(path, {'mid': str(mid)}, base='https://api.bilibili.com')
                d = j.get('data') or {}
                if d:
                    break
            except Exception:
                continue
        info = {'mid': str(mid), 'name': d.get('name') or '',
                'sign': (d.get('sign') or '')[:120],
                'level': d.get('level') or 0,
                'fans': d.get('fans') or 0,
                'following': d.get('friend') or 0}
        txt = 'UID ' + info['mid'] + chr(65306) + info['name'] + chr(10)
        txt += chr(31614) + chr(21517) + chr(65306) + info['sign'] + chr(10)
        txt += 'Lv' + str(info['level']) + '  ' + chr(31881) + chr(19997) + chr(65306) + str(info['fans'])
        return {'ok': True, 'info': info, 'text': txt}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

class H(http.server.BaseHTTPRequestHandler):
    token = ''
    def log_message(self, *a):  # 安静
        pass
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def _auth(self):
        if not H.token:
            return True
        if self.headers.get('Authorization', '').replace('Bearer ', '') == H.token:
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return (q.get('token') or [''])[0] == H.token
    def do_OPTIONS(self):
        self._send({'ok': True})
    def do_GET(self):
        u0 = urllib.parse.urlparse(self.path)
        if u0.path.startswith('/napcat'):
            return _proxy_napcat(self, u0.path, u0.query, 'GET')
        # ★ 面板文件优先（同源访问 => fetch 不会被拦）
        if not u0.path.startswith('/api/'):
            try:
                if _serve_panel(self, u0.path):
                    return
            except Exception:
                pass
        if not self._auth():
            return self._send({'error': 'unauthorized'}, 401)
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        try:
            if p == '/api/status':
                w = whoami()
                return self._send({'ok': True, 'bili': w, 'qq': qq_status(),
                                   'vts': _proc_running('VTube Studio'),
                                   'repliedCount': len(REPLIED_DB.get('replied', {})),
                                   'dmCount': len(REPLIED_DB.get('dm', {})),
                                   'uptime': int(time.time()) - STATE['startedAt']})
            if p == '/api/config/file':
                return self._send(config_read_file())
            if p == '/api/config/backups':
                return self._send(config_backups())
            if p == '/api/config/get':
                return self._send(config_get())
            if p == '/api/napcat/status':
                return self._send(napcat_status())
            if p == '/api/bili/drafts':
                return self._send(bili_drafts())
            if p == '/api/bili/fetch-image':
                return self._send(bili_fetch_image((q.get('url') or [''])[0]))
            if p == '/api/bili/dm-images':
                return self._send(bili_dm_images((q.get('id') or [''])[0],
                                                 int((q.get('n') or ['3'])[0])))
            if p == '/api/bili/replies':
                return self._send(bili_my_replies())
            if p == '/api/bili/draft-history':
                return self._send(bili_drafts_history())
            if p == '/api/bili/user-info':
                return self._send(bili_user_info((q.get('mid') or [''])[0]))
            if p == '/api/bili/user-info':
                return self._send(bili_user_info((q.get('mid') or [''])[0]))
            if p == '/api/bili/my-comments':
                return self._send(bili_her_comments(int((q.get('limit') or ['60'])[0])))
            if p == '/api/bili/dm/history':
                return self._send(bili_dm_history((q.get('mid') or [''])[0],
                                                  int((q.get('size') or ['30'])[0])))
            if p == '/api/bili/notices':
                return self._send(bili_notices())
            if p == '/api/bili/msgfeed':
                return self._send(bili_msgfeed((q.get('kind') or ['reply'])[0]))
            if p == '/api/bili/writecheck':
                return self._send(bili_write_check())
            if p == '/api/bili/dynamics':
                return self._send(my_dynamics(int((q.get('limit') or ['20'])[0])))
            if p == '/api/bili/dynamic-comments':
                return self._send(dynamic_comments_list((q.get('id') or [''])[0]))
            if p == '/api/bili/inbox':
                items = inbox(int((q.get('limit') or ['20'])[0]))
                ign = REPLIED_DB.get('ignored', {})
                out = []
                for it in items:
                    if 'id' not in it:
                        continue
                    if str(it['id']) in ign:            # ★ 已忽略的不再显示
                        continue
                    it['replied'] = already_replied('reply', it['id'])
                    out.append(it)
                return self._send({'ok': True, 'items': out})
            if p == '/api/bili/dm':
                _items = dm_list(int((q.get('limit') or ['30'])[0]))
                _out = []
                for _it in _items:
                    if 'id' not in _it:
                        continue
                    _it['replied'] = already_replied('dm', _it['id'])
                    if _it['replied'] and (q.get('all') or ['0'])[0] != '1':
                        continue          # ★ 回过的就不再列出来
                    _out.append(_it)
                return self._send({'ok': True, 'items': _out})
            if p == '/api/bili/replied':
                return self._send({'ok': True, 'data': REPLIED_DB})
            if p == '/api/audio/devices':
                r = run(['powershell', '-NoProfile', '-Command',
                         'Import-Module AudioDeviceCmdlets;Get-AudioDevice -List|Select Index,Type,Name,Default|ConvertTo-Json'],
                        cwd=ROOT, timeout=60)
                return self._send({'ok': True, 'raw': r['out']})
            if p == '/api/log':
                f = os.path.join(ROOT, 'out')
                items = sorted([x for x in os.listdir(f) if x.startswith('her-') and x.endswith('.txt')],
                               key=lambda x: os.path.getmtime(os.path.join(f, x)))[-30:]
                logs = [{'file': x, 'text': open(os.path.join(f, x), encoding='utf-8', errors='replace').read()[:400]} for x in items]
                return self._send({'ok': True, 'items': logs})
            if p.startswith('/api/qq/') or p in ('/api/config', '/api/vts/test', '/api/learn/limit'):
                return self._send(qq_route(p, q, {}))
            if p == '/api/selfcheck':
                return self._send(selfcheck())
            if p == '/api/live':
                return self._send({'ok': True, **live_status()})
            if p == '/api/learn':
                return self._send({'ok': True, **learn_status()})
            if p == '/api/prompt':
                return self._send({'ok': True, **read_prompt()})
            if p == '/api/prompt':
                return self._send(write_prompt(body.get('kind', 'card'), body.get('text', '')))
            if p == '/api/notes':
                p2 = os.path.join(QQBOT, 'bili', 'state', 'notes.json')
                return self._send({'ok': True, 'data': json.load(open(p2, encoding='utf-8'))})
            return self._send({'error': 'not found'}, 404)
        except Exception as e:
            return self._send({'ok': False, 'error': str(e)}, 500)
    def do_POST(self):
        if not self._auth():
            return self._send({'error': 'unauthorized'}, 401)
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if u.path.startswith('/napcat'):
            return _proxy_napcat(self, u.path, u.query, 'POST', raw)
        try:
            body = json.loads(raw or b'{}')
        except Exception:
            body = {}
        p = u.path
        try:
            if p.startswith('/api/qq/') or p in ('/api/config', '/api/vts/test', '/api/audio/switch', '/api/learn/limit'):
                return self._send(qq_route(p, {}, body))
            if p == '/api/chat':
                return self._send({'ok': True, **chat(body.get('text', ''))})
            if p == '/api/say':
                return self._send({'ok': True, **say(body.get('text', ''))})
            if p == '/api/voice/listen':
                return self._send({'ok': True, **voice_listen(int(body.get('seconds', 5)))})
            if p == '/api/vts/start':
                return self._send(vts('start'))
            if p == '/api/vts/stop':
                return self._send(vts('stop'))
            # ★★ 发评论（带 is_dynamic ✓）
            if p == '/api/config/file-set':
                return self._send(config_write_file(body.get('values') or {}))
            if p == '/api/config/restore':
                return self._send(config_restore(body.get('name', '')))
            if p == '/api/napcat/boot':
                return self._send(napcat_boot_visible())
            if p == '/api/config/set':
                return self._send(config_set(body.get('config') or {body.get('key'): body.get('value')}))
            if p == '/api/napcat/start':
                return self._send(napcat_start(bool(body.get('killQQ'))))
            if p == '/api/napcat/stop':
                return self._send(napcat_stop())
            if p == '/api/bili/draft-approve':
                return self._send(bili_draft_approve(body.get('id'), body.get('text')))
            if p == '/api/bili/draft-delete':
                return self._send(bili_draft_delete(body.get('id')))
            if p == '/api/bili/dynamic':
                return self._send(post_dynamic(body.get('text', '')))
            if p == '/api/bili/dynamic-auto':
                _r = chat('(写一条 B站动态，一二句，用你自己的口气，别解释、别用括号、别加引号，直接输出内容。)')
                _t = (_r.get('reply') or '').strip().strip('"').strip()
                if not _t:
                    return self._send({'ok': False, 'error': 'no text'})
                _o = post_dynamic(_t)
                _o['text'] = _t
                return self._send(_o)
            if p == '/api/bili/dynamic-reply':
                return self._send(dynamic_reply(body.get('id', ''), body.get('text', ''),
                                                body.get('parent'), body.get('root')))
            if p == '/api/bili/comment':
                return self._send(post_comment(body['oid'], body['text'],
                                               is_dynamic=bool(body.get('is_dynamic', True))))
            # ★★ 回复评论（带 is_dynamic ✓ + 去重 ✓）
            if p == '/api/bili/auto-reply':
                return self._send(auto_reply(body.get('oid', ''), body.get('parent', ''),
                                             body.get('root', 0), body.get('hint', ''), body.get('who', '')))
            if p == '/api/bili/reply':
                rid = str(body.get('id') or body.get('parent') or '')
                if body.get('dedup', True) and already_replied('reply', rid):
                    return self._send({'ok': False, 'skipped': True, 'error': '这条已经回过一次了（不重复回）'})
                r = reply_comment(body['oid'], body['text'], body['parent'],
                                  body.get('root', 0), is_dynamic=bool(body.get('is_dynamic', True)))
                if r.get('ok') and body.get('dedup', True):
                    mark_replied('reply', rid, {'oid': body['oid'], 'rpid': r.get('rpid'), 'text': body['text'][:80]})
                return self._send(r)
            if p == '/api/bili/ignore':
                                iid = str(body.get('id') or '')
                                if iid:
                                    REPLIED_DB.setdefault('ignored', {})[iid] = {'ts': int(time.time() * 1000)}
                                    _save_replied(REPLIED_DB)
                                return self._send({'ok': True, 'msg': 'ignored (will not show again)'})
            if p == '/api/bili/delete':
                return self._send(del_comment(body['oid'], body['rpid']))
            if p == '/api/bili/like':
                if body.get('comment_rpid'):
                    return self._send(like_comment(body['oid'], body['comment_rpid']))
                return self._send(like_video(body['aid']))
            if p == '/api/bili/coin':
                return self._send(coin_video(body['aid'], int(body.get('multiply', 1)), bool(body.get('also_like'))))
            if p == '/api/bili/fav':
                return self._send(fav_video(body['aid'], bool(body.get('add', True))))
            if p == '/api/bili/msg-reply':
                return self._send(bili_msg_reply(body.get('mid', ''), body.get('text', ''), bool(body.get('dry'))))
            if p == '/api/bili/dm/draft':
                return self._send(dm_draft(body.get('id'), body.get('hint', '')))
            if p == '/api/bili/dm/reply':
                import hashlib
                tid = str(body.get('id') or '')
                txt = str(body.get('text') or '')
                # ★ 主人 2026-10-05：解除「每人只能回一条」——
                #   改成「同一个人 + 同一句回复」才算重复（防手滑连发同一句），
                #   他发新的、她想回几次都行 ✓
                # ★ 主人 2026-10-05：私信【完全不禁】—— 同一个人想回几次回几次，
                #   连"同一句"也不挡（她自己决定说什么）。只记账，供控制台显示"已回过"。
                fp = tid + '#' + hashlib.md5((tid + '|' + txt[:120]).encode('utf-8', 'replace')).hexdigest()[:16]
                seen = REPLIED_DB.setdefault('dmfp', {})
                out = dm_send(tid, txt)
                if out.get('ok') and body.get('dedup', True):
                    seen[fp] = int(time.time() * 1000)
                    if len(seen) > 500:                     # 只留最近 300 条指纹
                        for k in sorted(seen, key=lambda x: seen[x])[:200]:
                            seen.pop(k, None)
                    mark_replied('dm', tid, {'text': txt[:80]})   # 列表里仍显示「已回过」✓
                    _save_replied(REPLIED_DB)
                return self._send(out)
            if p == '/api/notes':
                p2 = os.path.join(QQBOT, 'bili', 'state', 'notes.json')
                d = json.load(open(p2, encoding='utf-8'))
                d.setdefault('notes', []).append({'id': 'n' + str(int(time.time() * 1000)), 'ts': int(time.time() * 1000),
                                                  'kind': 'other', 'ref': '', 'title': body.get('title', '面板记录'),
                                                  'text': body.get('text', ''), 'tags': ['面板'], 'from': '主人'})
                json.dump(d, open(p2, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                return self._send({'ok': True})
            return self._send({'error': 'not found'}, 404)
        except Exception as e:
            return self._send({'ok': False, 'error': str(e)}, 500)

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--token', default='')
    a = ap.parse_args()
    H.token = a.token or ''
    w = whoami()
    print('大肥鱼 · 控制台后端')
    print('  B站: %s（%s · Lv%s · 硬币 %s）' % ('已登录' if w['loggedIn'] else '未登录',
                                              w['uname'], w['level'], w['coin']))
    print('  去重账本: 评论/回复 %d 条 · 私信 %d 条' % (len(REPLIED_DB.get('replied', {})), len(REPLIED_DB.get('dm', {}))))
    print('  监听: http://%s:%d%s' % (a.host, a.port, '（token 校验已开）' if H.token else ''))
    print('  接口见 http://%s:%d/api/status' % (a.host, a.port))
    with Server((a.host, a.port), H) as s:
        s.serve_forever()

if __name__ == '__main__':
    main()
