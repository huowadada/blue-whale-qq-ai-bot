#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qq.py —— 大肥鱼控制台的 QQ 后端（走 OneBot 11 / NapCat）
提供 13 个能力：status qrcode groups members history send mute kick restart config vts-test audio-switch learn-limit

连接方式：作为 WebSocket **客户端** 连到 NapCat 的 websocketServers
  地址在 qq.json 里（默认 ws://127.0.0.1:3001/?access_token=...）
  ★ 如果连不上 → 所有接口返回 {ok:false,error:'QQ 通道没开'}，面板会如实显示

NapCat 侧需要（onebot11_<QQ>.json）：
  "websocketServers": [{ "enable": true, "name":"console", "host":"127.0.0.1", "port":3001,
                         "messagePostFormat":"array", "reportSelfMessage":false,
                         "token":"<和这里一致>", "heartInterval":30000 }]
"""
import os, sys, json, time, socket, base64, threading, subprocess, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
QQ_CFG = os.path.join(HERE, 'qq.json')

DEFAULTS = {
    'wsUrl': 'ws://127.0.0.1:3001/',
    'token': 'YOUR_NAPCAT_ACCESS_TOKEN',
    'napcatDir': r'C:\ai PLAN\NapCat.Shell',
    'napcatExe': r'C:\ai PLAN\NapCat.Shell\NapCatWinBootMain.exe',
    'pythonw': r'C:\Users\28461\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe',
}


def load_cfg():
    c = dict(DEFAULTS)
    try:
        c.update(json.load(open(QQ_CFG, encoding='utf-8')))
    except Exception:
        pass
    return c


CFG = load_cfg()
LOCK = threading.Lock()
_ws = None
_echo = 0
_waiting = {}
_events = []
_connected = False
_last_err = ''


# ───────────────── 极简 WebSocket 客户端（零依赖，够用） ─────────────────
class MiniWS:
    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.host = u.hostname or '127.0.0.1'
        self.port = u.port or 80
        self.path = (u.path or '/') + (('?' + u.query) if u.query else '')
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ('GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
               'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n'
               % (self.path, self.host, self.port, key))
        self.sock.sendall(req.encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.sock.recv(4096)
        if b'101' not in buf.split(b'\r\n')[0]:
            raise RuntimeError('handshake failed: ' + buf.split(b'\r\n')[0].decode('latin1', 'replace'))
        self.buf = buf.split(b'\r\n\r\n', 1)[1]
        self.sock.settimeout(30)

    def send(self, text):
        data = text.encode('utf-8')
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126); head += n.to_bytes(2, 'big')
        else:
            head.append(0x80 | 127); head += n.to_bytes(8, 'big')
        mask = os.urandom(4)
        head += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(head) + masked)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        b1, b2 = self._read(2)
        op = b1 & 0x0F
        ln = b2 & 0x7F
        if ln == 126:
            ln = int.from_bytes(self._read(2), 'big')
        elif ln == 127:
            ln = int.from_bytes(self._read(8), 'big')
        if b2 & 0x80:
            mask = self._read(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._read(ln)))
        else:
            data = self._read(ln)
        if op == 0x8:
            raise ConnectionError('server closed')
        if op == 0x9:            # ping -> pong
            try:
                self.sock.sendall(b'\x8a\x80' + os.urandom(4))
            except Exception:
                pass
            return self.recv()
        return data.decode('utf-8', 'replace')

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def _reader():
    global _ws, _connected, _last_err
    while True:
        try:
            _ws = MiniWS(CFG['wsUrl'])
            _connected = True
            _last_err = ''
            while True:
                msg = _ws.recv()
                try:
                    j = json.loads(msg)
                except Exception:
                    continue
                e = j.get('echo')
                if e is not None and e in _waiting:
                    _waiting[e] = j
                else:
                    _events.append(j)
                    if len(_events) > 300:
                        del _events[:150]
        except Exception as ex:
            _connected = False
            _last_err = str(ex)[:200]
            _ws = None
            time.sleep(5)


def start():
    t = threading.Thread(target=_reader, daemon=True)
    t.start()


def call(action, params=None, timeout=15):
    """同步调一个 OneBot 动作"""
    global _echo
    if not _connected or _ws is None:
        return {'ok': False, 'error': 'QQ 通道没开（NapCat 的 websocketServers 没启用）'}
    with LOCK:
        _echo += 1
        eid = 'e%d' % _echo
        _waiting[eid] = None
    try:
        _ws.send(json.dumps({'action': action, 'params': params or {}, 'echo': eid}, ensure_ascii=False))
    except Exception as ex:
        return {'ok': False, 'error': '发送失败：%s' % ex}
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = _waiting.get(eid)
        if r is not None:
            _waiting.pop(eid, None)
            return {'ok': r.get('status') == 'ok' or r.get('retcode') == 0, 'data': r.get('data'),
                    'raw': r, 'error': None if (r.get('status') == 'ok' or r.get('retcode') == 0) else (r.get('message') or r.get('wording'))}
        time.sleep(0.05)
    _waiting.pop(eid, None)
    return {'ok': False, 'error': '超时（%ss）' % timeout}


# ───────────────── 13 个能力 ─────────────────
def qq_status():
    info = call('get_login_info', timeout=8)
    st = call('get_status', timeout=8)
    return {
        'ok': True,
        'connected': _connected,
        'error': _last_err or None,
        'qq': (info.get('data') or {}).get('user_id') if info.get('ok') else None,
        'nickname': (info.get('data') or {}).get('nickname') if info.get('ok') else None,
        'online': bool(st.get('ok') and (st.get('data') or {}).get('online')),
        'good': bool(st.get('ok') and (st.get('data') or {}).get('good')),
        'wsUrl': CFG['wsUrl'],
    }


def qq_qrcode():
    """NapCat 扫码登录：优先用 WebUI 的二维码接口，没有就告诉你手动方式"""
    return {'ok': False, 'error': '二维码：NapCat 未开 WebUI 二维码接口。'
                                  '请在浏览器打开 http://127.0.0.1:6099 扫码（token 见 config\\webui.json）'}


def qq_groups():
    r = call('get_group_list')
    if not r.get('ok'):
        return r
    out = [{'id': str(g.get('group_id')), 'name': g.get('group_name'),
            'count': g.get('member_count'), 'max': g.get('max_member_count'),
            'owner': str(g.get('owner_id') or '')} for g in (r.get('data') or [])]
    out.sort(key=lambda x: -(x['count'] or 0))
    return {'ok': True, 'groups': out}


def qq_members(gid):
    r = call('get_group_member_list', {'group_id': int(gid)}, timeout=25)
    if not r.get('ok'):
        return r
    out = [{'id': str(m.get('user_id')), 'name': m.get('card') or m.get('nickname'),
            'nick': m.get('nickname'), 'role': m.get('role'), 'level': m.get('level')}
           for m in (r.get('data') or [])]
    return {'ok': True, 'members': out}


def qq_history(gid, n=30):
    r = call('get_group_msg_history', {'group_id': int(gid), 'count': int(n)}, timeout=20)
    if not r.get('ok'):
        return r
    msgs = (r.get('data') or {}).get('messages') or []
    out = []
    for m in msgs:
        segs = m.get('message') or []
        txt = ''
        if isinstance(segs, list):
            for s in segs:
                if isinstance(s, dict):
                    t = s.get('type')
                    d = s.get('data') or {}
                    if t == 'text':
                        txt += d.get('text', '')
                    elif t == 'image':
                        txt += '[图片]'
                    elif t == 'face':
                        txt += '[表情]'
                    elif t == 'at':
                        txt += '@' + str(d.get('qq', ''))
        else:
            txt = str(segs)
        out.append({'who': str((m.get('sender') or {}).get('user_id', '')),
                    'name': (m.get('sender') or {}).get('card') or (m.get('sender') or {}).get('nickname'),
                    'text': txt, 'ts': m.get('time')})
    return {'ok': True, 'messages': out}


def qq_send(target, text, kind='group', image=None, file=None):
    """发消息。target=群号或QQ号；image/file 传本地绝对路径"""
    msg = []
    if text:
        msg.append({'type': 'text', 'data': {'text': text}})
    if image:
        msg.append({'type': 'image', 'data': {'file': 'file:///' + image.replace('\\', '/')}})
    if file:
        msg.append({'type': 'file', 'data': {'file': 'file:///' + file.replace('\\', '/')}})
    if not msg:
        return {'ok': False, 'error': '内容是空的'}
    act = 'send_group_msg' if kind == 'group' else 'send_private_msg'
    key = 'group_id' if kind == 'group' else 'user_id'
    return call(act, {key: int(target), 'message': msg})


def qq_mute(gid, uid, seconds):
    if int(seconds) <= 0:
        return call('set_group_ban', {'group_id': int(gid), 'user_id': int(uid), 'duration': 0})
    return call('set_group_ban', {'group_id': int(gid), 'user_id': int(uid), 'duration': int(seconds)})


def qq_kick(gid, uid, reject=False):
    return call('set_group_kick', {'group_id': int(gid), 'user_id': int(uid),
                                   'reject_add_request': bool(reject)})


def qq_restart():
    """重启 NapCat（不杀 QQ 本体，走它自己的接口；没有就提示手动）"""
    r = call('set_restart', {'delay': 1000}, timeout=8)
    if r.get('ok'):
        return {'ok': True, 'msg': 'NapCat 正在重启（几秒后自己回来）'}
    return {'ok': False, 'error': '这个 NapCat 不支持远程重启：%s' % (r.get('error') or '')}


# ───────────────── 配置 / 音频 / 学习上限（另外 3 个） ─────────────────
CONFIG_FILE = os.path.join(os.path.dirname(HERE), 'config.json')      # avatar/config.json
LEARN_CARD = r'C:\Users\28461\Documents\deepseek-harness\default-workspace\qqbot\AGENTS.md'


def get_config():
    try:
        return {'ok': True, 'config': json.load(open(CONFIG_FILE, encoding='utf-8'))}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def set_config(patch):
    try:
        c = json.load(open(CONFIG_FILE, encoding='utf-8'))
        _deep_merge(c, patch or {})
        json.dump(c, open(CONFIG_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _deep_merge(a, b):
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)
        else:
            a[k] = v


def vts_test():
    """让皮套嘴动一下：说一个短促的音 """
    try:
        tts = os.path.join(os.path.dirname(HERE), 'tts.mjs')
        node = r'C:\Users\28461\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
        r = subprocess.run([node, tts, '啊'], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return {'ok': r.returncode == 0, 'out': (r.stdout or '')[-200:], 'err': (r.stderr or '')[-200:]}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def audio_switch(index, kind='Playback'):
    try:
        ps = ("Import-Module AudioDeviceCmdlets;"
              "Set-AudioDevice -Index %d" % int(index))
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=40, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return {'ok': r.returncode == 0, 'out': (r.stdout or '')[-200:], 'err': (r.stderr or '')[-200:]}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def learn_limits(action='get', limit=None):
    """读/改她的每日学习上限（写进卡片 ✓ 每轮注入 ✓ 立即生效）"""
    try:
        s = open(LEARN_CARD, encoding='utf-8').read()
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    import re
    m = re.search(r'一天最多记\s*\*{0,2}(\d+)\s*条', s)
    cur = int(m.group(1)) if m else 0
    if action == 'get' or limit is None:
        return {'ok': True, 'limit': cur}
    n = int(limit)
    s2 = re.sub(r'(一天最多记\s*\*{0,2})\d+(\s*条)', r'\g<1>%d\g<2>' % n, s)
    if s2 == s:
        return {'ok': False, 'error': '没找到可替换的上限文本'}
    open(LEARN_CARD, 'w', encoding='utf-8').write(s2)
    return {'ok': True, 'limit': n, 'msg': '上限已改为 %d（下一条消息生效）' % n}


def events(kind=None, limit=50):
    ev = [e for e in _events if (kind is None or e.get('post_type') == kind)]
    return {'ok': True, 'events': ev[-limit:]}


if __name__ == '__main__':
    start()
    time.sleep(2)
    print(json.dumps(qq_status(), ensure_ascii=False, indent=2))
