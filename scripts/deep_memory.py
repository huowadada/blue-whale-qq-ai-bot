# -*- coding: utf-8 -*-
r"""大肥鱼的【深层记忆】脚本（主人 2026-10-05 新增，独立文件）
═══════════════════════════════════════════════════════════════
两个模式：
  ① python deep_memory.py --backfill [--pages N] [--n M]
     往回灌：从最近的消息开始【一页一页往回翻】，把所有历史（含她自己发的）
     灌进档案 qqbot\history\<群>.md / .jsonl 和 all.md（去重 ✓ 永久保存 ✓）
  ② python deep_memory.py --forget [--min 10] [--max 20]
     每天随机遗忘：从她的经验本 notes.json 里【随机删掉 10~20 条】
     （像人一样会淡忘；被忘的写进遗忘日志，主人能查，不给她看）

位置（你要的）：
  脚本： C:\app\dfy\deep_memory.py
  档案： C:\Users\28461\Documents\deepseek-harness\default-workspace\qqbot\history\
  遗忘日志：C:\app\dfy\memory-forget.log
"""
import os, sys, json, time, random, hashlib, urllib.request

PANEL = 'http://127.0.0.1:8787'
HIST = r'C:\Users\28461\Documents\deepseek-harness\default-workspace\qqbot\history'
NOTES = r'C:\Users\28461\Documents\deepseek-harness\default-workspace\qqbot\bili\state\notes.json'
FLOG = r'C:\app\dfy\memory-forget.log'
GROUPS = ['YOUR_GROUP_ID', 'YOUR_GROUP_ID2']
KEEP = 5000          # 档案每个群最多留多少条


def log(p, msg):
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%m-%d %H:%M:%S ') + str(msg) + '\n')
    except Exception:
        pass


def get(url):
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def norm(m):
    """兼容两种形状：面板归一化 {who,name,text,ts} / NapCat 原始 {user_id,sender,raw_message,time}"""
    if not isinstance(m, dict):
        return None
    if 'text' in m and ('who' in m or 'ts' in m):
        return {'who': str(m.get('who') or ''), 'name': str(m.get('name') or ''),
                'text': str(m.get('text') or ''), 'ts': int(m.get('ts') or 0),
                'seq': int(m.get('seq') or m.get('message_seq') or 0)}
    s = m.get('sender') or {}
    name = s.get('card') or s.get('nickname') or str(m.get('user_id') or '')
    txt = m.get('raw_message')
    if txt is None:
        seg = m.get('message')
        if isinstance(seg, list):
            txt = ' '.join(str(x.get('data', {}).get('text', '')) if isinstance(x, dict) else '' for x in seg)
        else:
            txt = str(seg or '')
    return {'who': str(m.get('user_id') or s.get('user_id') or ''), 'name': str(name),
            'text': str(txt or ''), 'ts': int(m.get('time') or 0),
            'seq': int(m.get('real_seq') or m.get('message_seq') or m.get('seq') or m.get('msgSeq') or m.get('msg_seq') or m.get('message_id') or 0)}


def fp(m):
    return hashlib.md5(('%s|%s|%s' % (m.get('ts'), m.get('who'), m.get('text'))).encode('utf-8', 'replace')).hexdigest()[:16]


def load(group):
    p = os.path.join(HIST, group + '.jsonl')
    out, seen = [], set()
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            out.append(o)
            seen.add(fp(o))
    return out, seen


def save(group, msgs):
    os.makedirs(HIST, exist_ok=True)
    msgs.sort(key=lambda m: int(m.get('ts') or 0))
    msgs = msgs[-KEEP:]
    with open(os.path.join(HIST, group + '.jsonl'), 'w', encoding='utf-8') as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + '\n')
    with open(os.path.join(HIST, group + '.md'), 'w', encoding='utf-8') as f:
        f.write('# 群 %s 的完整聊天档案（她重启前的消息都在这）\n' % group)
        f.write('> 自动维护：每 5 分钟追加 + 往回翻补齐。共 %d 条。\n\n' % len(msgs))
        for m in msgs:
            t = time.strftime('%m-%d %H:%M', time.localtime(int(m.get('ts') or 0)))
            f.write('[%s] %s(%s): %s\n' % (t, m.get('name') or '?', m.get('who') or '?',
                                           (m.get('text') or '').replace('\n', ' ')))
    return len(msgs)


def backfill(pages=40, n=50):
    total_new = 0
    merged = []
    for gid in GROUPS:
        old, seen = load(gid)
        got = 0
        seq = None                            # ★ 第一页走 raw=1（拿带 message_seq 的原始页）
        for page in range(pages):
            if seq is None:
                url = '%s/api/qq/history?gid=%s&n=%d&raw=1' % (PANEL, gid, n)
            else:
                url = '%s/api/qq/history?gid=%s&n=%d&seq=%d' % (PANEL, gid, n, seq)
            try:
                j = get(url)
            except Exception as e:
                log(r'C:\app\dfy\deep-memory.log', '群 %s 第 %d 页失败: %s' % (gid, page + 1, e))
                break
            raw = None
            if isinstance(j, dict):
                raw = j.get('messages')
                if raw is None and isinstance(j.get('raw'), dict):
                    raw = j['raw'].get('messages')
                if raw is None and isinstance(j.get('raw'), list):
                    raw = j['raw']
                if raw is None and isinstance(j.get('raw'), dict):
                    _d = j['raw'].get('data')
                    if isinstance(_d, dict):
                        raw = _d.get('messages')
                    elif isinstance(_d, list):
                        raw = _d
            if not raw:
                if page == 0:                 # 第一页没给 → 退回不带 seq 的旧路（只拿最新）
                    try:
                        j2 = get('%s/api/qq/history?gid=%s&n=%d' % (PANEL, gid, n))
                        raw = (j2 or {}).get('messages') or ((j2 or {}).get('raw') or {}).get('messages')
                    except Exception:
                        raw = None
                if not raw:
                    log(r'C:\app\dfy\deep-memory.log', '群 %s 第 %d 页空，停' % (gid, page + 1))
                    break
            msgs = [x for x in (norm(m) for m in raw) if x and x.get('text')]
            fresh = [m for m in msgs if fp(m) not in seen]
            for m in fresh:
                seen.add(fp(m))
                old.append(m)
            got += len(fresh)
            # ★ seq 候选（NapCat 有些版本给 message_seq，有些给 real_seq / message_id）
            seqs = []
            for m in raw:
                if not isinstance(m, dict):
                    continue
                for k in ('real_seq', 'message_seq', 'seq', 'message_id', 'msg_seq', 'msgSeq'):
                    v = m.get(k)
                    try:
                        if v is not None and int(v) > 0:
                            seqs.append(int(v))
                            break
                    except Exception:
                        continue
            if page == 0 and not fresh and len(msgs) == 0:
                log(r'C:\app\dfy\deep-memory.log', '群 %s 本页没有可用文本，继续' % gid)
            # ★ NapCat 一页最多 ~48 条，不能拿“不足 n”当到底 ✗
            if not seqs:
                log(r'C:\app\dfy\deep-memory.log', '群 %s 第 %d 页拿不到 seq，停' % (gid, page + 1))
                break
            newseq = min(seqs)
            if seq is not None and newseq >= seq:
                # 没有更早的了：用 newseq-1 再试一次，仍不前进就停
                if seq is not None and newseq - 1 >= seq:
                    log(r'C:\app\dfy\deep-memory.log', '群 %s 第 %d 页 seq 不前进(%d)，停' % (gid, page + 1, newseq))
                    break
                newseq = seq - 1
            seq = newseq
        cnt = save(gid, old)
        total_new += got
        merged.extend(old)
        log(r'C:\app\dfy\deep-memory.log', '群 %s：档案 %d 条，本轮新增 %d 条（翻到第 %d 页）' % (gid, cnt, got, page + 1))
    if merged:
        merged.sort(key=lambda m: int(m.get('ts') or 0))
        merged = merged[-8000:]
        with open(os.path.join(HIST, 'all.md'), 'w', encoding='utf-8') as f:
            f.write('# 所有群的完整档案（按时间合并）\n> 共 %d 条。\n\n' % len(merged))
            for m in merged:
                t = time.strftime('%m-%d %H:%M', time.localtime(int(m.get('ts') or 0)))
                f.write('[%s] %s(%s): %s\n' % (t, m.get('name') or '?', m.get('who') or '?',
                                               (m.get('text') or '').replace('\n', ' ')))
    return total_new


def forget(mn=10, mx=20):
    if not os.path.exists(NOTES):
        log(FLOG, 'notes.json 不在')
        return 0
    d = json.load(open(NOTES, encoding='utf-8'))
    arr = d.get('notes') if isinstance(d, dict) else d
    if not isinstance(arr, list) or not arr:
        return 0
    k = min(len(arr), random.randint(mn, mx))
    idx = sorted(random.sample(range(len(arr)), k), reverse=True)
    gone = [arr[i] for i in idx]
    for i in idx:
        del arr[i]
    if isinstance(d, dict):
        d['notes'] = arr
    else:
        d = arr
    json.dump(d, open(NOTES, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    log(FLOG, '今天忘了 %d 条（剩 %d 条）：' % (k, len(arr)))
    for g in gone:
        log(FLOG, '   · [' + str(g.get('kind') or '?') + '] ' + str(g.get('text') or '')[:90])
    return k


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--backfill' in a:
        pages = 40
        n = 50
        if '--pages' in a:
            pages = int(a[a.index('--pages') + 1])
        if '--n' in a:
            n = int(a[a.index('--n') + 1])
        print('往回灌：每个群最多翻 %d 页 x %d 条' % (pages, n))
        print('新增 %d 条' % backfill(pages, n))
    elif '--forget' in a:
        mn, mx = 10, 20
        if '--min' in a:
            mn = int(a[a.index('--min') + 1])
        if '--max' in a:
            mx = int(a[a.index('--max') + 1])
        print('今天忘了 %d 条' % forget(mn, mx))
    else:
        print(__doc__)
