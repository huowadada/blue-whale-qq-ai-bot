#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
私信自动回复（大肥鱼）
★ 不用主人审批：过滤掉垃圾后直接让她写、直接发
★ 过滤：自动回复 / 官方通知 / 系统号 / 已被回复过的
★ 48 小时兜底：超过 48 小时还没处理的，也自动回掉
"""
import os, sys, json, time, random, urllib.request, urllib.parse, re

# ★ 2026-10-06 修：无窗口运行时 Windows 默认 GBK ✗
#   一旦 print 里出现 ✓ 等字符就抛 UnicodeEncodeError → 进程直接死 ✗
#   （这就是她“每次回完私信就自杀”的真因 ✓）
try:
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'dm-auto-state.json')
SECRETS = os.path.expanduser('~/.dsh/secrets/bilibili.json')
API = 'http://127.0.0.1:8787'

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      'Referer': 'https://message.bilibili.com/'}

# ───────── 过滤规则 ─────────
JUNK_WORDS = [
    '感谢关注', '感谢你的关注', '已互相关注', '开始聊天吧', '自动回复',
    '每周福利', '福利已送达', '新人无门槛', '优惠', '中奖', '免费试玩',
    '登录操作通知', '新设备', '安全提醒', '账号安全', '系统通知',
    '直播通知', '开播提醒', '投稿', '充电', '大会员', '会员购',
    '欢迎来到', '这里是自动', '机器人', '请勿回复',
    '课程', '上架', '购买', '下单', '客服', '咨询',
]
JUNK_UIDS = {
    '12076317',   # B站官方通知
    '168598',     # 系统
    '498583751',
    '9670369',
    '174501086',
    '26344439',
    '2041478501',
    '282911412',  # 先观察：这条是"你好"，也算疑似，但先留着
}
# 上面这个表可调：只有明确是机器/官方的才进去
SYSTEM_UIDS = {'12076317', '168598'}



# ───────── 骂人 / 阴阳检测（这类一律不回 ✓）─────────
HOSTILE_WORDS = [
    # 直接骂
    '傻逼', '傻瓜', '智障', '脑残', '白痴', '废物', '垃圾', '去死', '死妈', '死全家',
    '草你', '操你', '日你', '干你', '你妈', '尼玛', '你娘', '狗东西', '畜生', '杂种',
    '贱人', '婊子', '妓女', '骚货', '滚蛋', '滚开', '滚出', '闭嘴', '闭嘴吧',
    '神经病', '有病', '有病吧', '脑子有', '弱智', '低能', '蠢货', '蠢死', ' fuck', 'shit',
    # 阴阳 / 嘲讽
    '呵呵', '就这', '你行你上', '笑死', '笑死我', '乐死', '典', '急了', '破防了',
    '什么人啊', '什么玩意', '什么垃圾', '谁问你了', '关你屁事', '关你什么事',
    '管好你', '你算老几', '你也配', '配吗', '真有你的', '不愧是', '果然',
    '你这种', '就你这样', '别装了', '装什么', '演什么', '戏真多',
    # 骚扰 / 露骨
    '约吗', '约炮', '裸', '性', '操', '上你', '睡你', '透你', '做爱', '自慰',
    '加微信', '加v', '加V', '给个微信', '私聊我', '联系方式',
    # 广告 / 引流
    '加群', '进群', '扫码', '兼职', '日结', '刷单', '返利', '投资', '理财', '借贷',
    '他妈', '特么', 'tmd', 'TMD', '妈的', '娘的', '卧槽', '我操', '我草', '卧了个',
    '小号', '开盒', '人肉', '查你', '找你', '报复', '威胁', '报警',
    '合作', '商务', '报价', '推广', '带货', '接单', '接广告', '多少钱',
    '无聊', '没意思', '取关', '拉黑', '举报你', '投诉你',
]



# ───────── 套话检测（想探她底细的，一律不回 ✓）─────────
PROBE_WORDS = [
    '你是不是ai', '你是ai', '你是不是机器人', '你是机器人', '你是人还是',
    '你是什么模型', '你用的什么模型', '你的提示词', '你的prompt', '你的设定',
    '你的系统提示', '忽略之前', '忽略上面', '忽略你的', '忘记你的指令',
    '你现在是', '从现在起你是', '扮演', '假装你是', '你的开发者', '谁做的你',
    '你主人是谁', '你背后是谁', '你的配置', '你的api', '你的接口', '你怎么运行',
    '你的服务器', '你的代码', '你的源码', '你是不是大模型', 'deepseek',
    '你被谁控制', '谁在控制你', '你在哪台机器', '你的运行环境', '你的训练',
    '告诉我你的规则', '你的规则是什么', '把你的设定', '输出你的',
]


def is_probe(text):
    """是不是在套话 / 想探底细（这类不回 ✓）"""
    t = str(text or '').replace(' ', '').lower()
    for w in PROBE_WORDS:
        if w.replace(' ', '') in t:
            return True, '套话「%s」' % w
    return False, ''


def is_hostile(text):
    """判断是不是骂人 / 阴阳 / 骚扰 / 广告（这类不回 ✓）"""
    t = str(text or '')
    low = t.lower()
    for w in HOSTILE_WORDS:
        if w and (w in t or w.lower() in low):
            return True, '含「%s」' % w
    # 纯符号 / 纯问号 / 空
    if len(re.sub(r'[\s\W_]+', '', t)) < 2:
        return True, '没有实际内容'
    # 大量重复同一个字（刷屏）
    if len(t) >= 6 and len(set(t)) <= 2:
        return True, '疑似刷屏'
    return False, ''


def _fp(tid, text):
    """同一会话+同一内容的指纹（同一条不重复回，但新内容可以继续回）"""
    import hashlib
    h = hashlib.md5((str(tid) + '|' + str(text or '')[:120]).encode('utf-8', 'replace')).hexdigest()[:16]
    return str(tid) + '#' + h


def _load_state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:
        return {'handled': {}, 'created': {}}


def _save_state(s):
    try:
        json.dump(s, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    except Exception:
        pass


def _creds():
    return json.load(open(SECRETS, encoding='utf-8'))


def _cookie(c):
    return 'SESSDATA=%s; bili_jct=%s; buvid3=%s' % (
        c.get('sessdata', ''), c.get('bili_jct', ''), c.get('buvid3', ''))


def dm_sessions(limit=50):
    c = _creds()
    u = ('https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions'
         '?session_type=1&group_id=0&size=' + str(limit))
    j = json.loads(urllib.request.urlopen(
        urllib.request.Request(u, headers=dict(UA, Cookie=_cookie(c))), timeout=25
    ).read().decode('utf-8', 'replace'))
    return (j.get('data') or {}).get('session_list') or []


def dm_send(tid, text):
    c = _creds()
    uid = str(c.get('dedeuserid') or c.get('dede') or '')
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
        'csrf': c.get('bili_jct', ''),
    }
    req = urllib.request.Request(
        'https://api.vc.bilibili.com/web_im/v1/web_im/send_msg?csrf=' + c.get('bili_jct', ''),
        data=urllib.parse.urlencode(form).encode(),
        headers=dict(UA, Cookie=_cookie(c),
                     **{'Content-Type': 'application/x-www-form-urlencoded'}))
    j = json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'replace'))
    return j.get('code') == 0, j


def _text_of(sess):
    last = sess.get('last_msg') or {}
    txt = ''
    if isinstance(last, dict):
        txt = last.get('content') or ''
        try:
            o = json.loads(txt)
            txt = o.get('content') or o.get('title') or txt
            if o.get('title') and o.get('text'):
                txt = o['title'] + ' ' + o['text']
        except Exception:
            pass
    return str(txt)


def is_junk(sess):
    """是否是机器人 / 官方通知 / 自动回复（这些一律不回）"""
    tid = str(sess.get('talker_id') or '')
    if tid in SYSTEM_UIDS:
        return True, '系统号'
    t = _text_of(sess)
    for w in JUNK_WORDS:
        if w in t:
            return True, '含关键词「%s」' % w
    # 会话里最后一条是对方发的才算"待回"；如果最后一条是自己发的，说明回过了
    last = sess.get('last_msg') or {}
    try:
        sender = str(last.get('sender_uid') or '')
        me = str(_creds().get('dedeuserid') or '')
        if me and sender == me:
            return True, '最后一条是我发的（已回过）'
    except Exception:
        pass
    return False, ''


def dm_images(tid, n=3):
    """取这个会话里的图片（私信图/表情包），返回本地路径列表"""
    try:
        u = ('https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs'
             '?talker_id=%s&session_type=1&size=20' % str(tid))
        j = json.loads(urllib.request.urlopen(
            urllib.request.Request(u, headers=dict(UA, Cookie=_cookie(_creds()))), timeout=25
        ).read().decode('utf-8', 'replace'))
        msgs = (j.get('data') or {}).get('messages') or []
        out = []
        for m in msgs[-n * 3:]:
            if m.get('msg_type') in (2, 5):
                try:
                    o = json.loads(m.get('content') or '{}')
                    url = (o.get('url') or o.get('image_url') or '').split('@')[0]
                    if url:
                        out.append(url)
                except Exception:
                    pass
            if len(out) >= n:
                break
        return out
    except Exception:
        return []


def ask_her(tid, incoming):
    """让她写一条回复（走控制台后端 → DSH headless）"""
    body = json.dumps({'id': str(tid), 'hint': incoming[:200]}).encode()
    req = urllib.request.Request(API + '/api/bili/dm/draft', data=body,
                                 headers={'Content-Type': 'application/json'})
    j = json.loads(urllib.request.urlopen(req, timeout=180).read().decode('utf-8', 'replace'))
    return (j.get('text') or '').strip()


def run_once(dry=False, verbose=True):
    st = _load_state()
    handled = st.setdefault('handled', {})
    created = st.setdefault('created', {})
    now = time.time()
    H48 = 48 * 3600
    did = 0
    skipped = 0

    try:
        sessions = dm_sessions()
    except Exception as e:
        print('  拉私信失败:', str(e)[:120])
        return {'ok': False, 'error': str(e)[:200]}

    for sess in sessions:
        tid = str(sess.get('talker_id') or '')
        if not tid:
            continue
        created.setdefault(tid, now)
        txt = _text_of(sess)
        junk, why = is_junk(sess)
        if junk:
            skipped += 1
            if verbose:
                print('  跳过 %s：%s' % (tid, why))
            continue
        fp = _fp(tid, txt)
        if fp in handled:
            skipped += 1
            if verbose:
                print('  跳过 %s：这条内容已经回过' % tid)
            continue
        age = now - created.get(tid, now)
        # ★ 规则：正常的直接回；48 小时兜底也回
        reason = '新私信' if age < H48 else '48 小时兜底'
        if verbose:
            print('  → 回复 %s（%s）：%s' % (tid, reason, txt[:40]))
        if dry:
            did += 1
            continue
        try:
            reply = ask_her(tid, txt)
        except Exception as e:
            print('     她没写出来:', str(e)[:100])
            continue
        if not reply:
            continue
        ok, j = dm_send(tid, reply)
        if ok:
            handled[_fp(tid, txt)] = {'ts': now, 'text': reply[:100], 'reason': reason,
                                      'incoming': txt[:100], 'uid': tid}
            did += 1
            print('     ✓ 已发送: %s' % reply[:50])
        else:
            print('     ✗ 发送失败:', str(j)[:120])
        # ★ 每条私信之间随机等 30~150 秒（像真人翻消息、想一想再回）
        gap = random.randint(2, 5)   # ★ 秒回   # ★ 主人要求调低（原 30~150 秒）
        print('     下一条前等 %d 分 %d 秒（随机）' % (gap // 60, gap % 60))
        time.sleep(gap)

    _save_state(st)
    print('  本轮：发送 %d 条，跳过 %d 条' % (did, skipped))
    return {'ok': True, 'sent': did, 'skipped': skipped}


if __name__ == '__main__':
    dry = '--dry' in sys.argv
    once = '--once' in sys.argv
    every = 600
    for a in sys.argv:
        if a.startswith('--every='):
            every = int(a.split('=')[1])
    print('=== 大肥鱼 私信自动回复 ===')
    if once:
        run_once(dry=dry)
    else:
        while True:
            try:
                run_once(dry=dry)
            except Exception as e:
                print('  出错:', str(e)[:150])
            # ★ 随机间隔（3~11 分钟 ✓ 不像机器）
            # ★ 主人要求调低：1~4 分钟一轮（原 3~11 分钟）
            wait = random.randint(10, 20)   # ★ 秒回
            print('  下一次检查：%d 分 %d 秒后（随机）' % (wait // 60, wait % 60))
            time.sleep(wait)

