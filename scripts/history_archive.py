# -*- coding: utf-8 -*-
"""把她账号里的群聊历史，定期抓下来存成【她自己能读】的档案。
- 数据源：面板 /api/qq/history（实测好用）→ 它再问 NapCat get_group_msg_history
- 落盘：工作区 qqbot\history\<群号>.md（人看的）+ .jsonl（机器去重）
       还有 qqbot\history\all.md（所有群合并，按时间）
- 去重：按 (时间, 发言人, 内容) 指纹；只追加新的
- 用法：watchdog 每 5 分钟跑一次（计划任务 DaFeiYuHistory）
"""
import os, json, time, hashlib, urllib.request, urllib.error

PANEL = 'http://127.0.0.1:8787'
HIST = r'C:\Users\28461\Documents\deepseek-harness\default-workspace\qqbot\history'
LOG = r'C:\app\dfy\history-archive.log'
GROUPS = ['YOUR_GROUP_ID2', 'YOUR_GROUP_ID']
KEEP = 400          # 每个群保留最近多少条
FETCH = 60          # 每次抓多少条


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%m-%d %H:%M:%S ') + str(msg) + '\n')
    except Exception:
        pass


def fp(m):
    return hashlib.md5(('%s|%s|%s' % (m.get('ts'), m.get('who'), m.get('text'))).encode('utf-8', 'replace')).hexdigest()[:16]


def fetch(gid):
    url = '%s/api/qq/history?gid=%s&n=%d' % (PANEL, gid, FETCH)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            j = json.loads(r.read().decode('utf-8', 'replace'))
    except Exception as e:
        log('群 %s 抓取失败: %s' % (gid, e))
        return None
    if not isinstance(j, dict) or not j.get('ok'):
        log('群 %s 返回异常: %s' % (gid, str(j)[:120]))
        return None
    msgs = j.get('messages')
    return msgs if isinstance(msgs, list) else []


def fmt(m):
    ts = m.get('ts')
    try:
        t = time.strftime('%m-%d %H:%M', time.localtime(int(ts)))
    except Exception:
        t = '??'
    return '[%s] %s(%s): %s' % (t, m.get('name') or '?', m.get('who') or '?', (m.get('text') or '').replace('\n', ' '))


def main():
    os.makedirs(HIST, exist_ok=True)
    total_new = 0
    merged = []
    for gid in GROUPS:
        msgs = fetch(gid)
        if msgs is None:
            continue
        jl = os.path.join(HIST, gid + '.jsonl')
        seen = set()
        old = []
        if os.path.exists(jl):
            with open(jl, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    old.append(o)
                    seen.add(fp(o))
        new = [m for m in msgs if fp(m) not in seen]
        allm = old + new
        # 按时间排 + 截断
        def key(m):
            try:
                return int(m.get('ts') or 0)
            except Exception:
                return 0
        allm.sort(key=key)
        allm = allm[-KEEP:]
        with open(jl, 'w', encoding='utf-8') as f:
            for m in allm:
                f.write(json.dumps(m, ensure_ascii=False) + '\n')
        with open(os.path.join(HIST, gid + '.md'), 'w', encoding='utf-8') as f:
            f.write('# 群 %s 的聊天档案（她重启前的消息也在这里）\n' % gid)
            f.write('> 每 5 分钟自动追加一次；最新挂在最后。共 %d 条（保留最近 %d 条）。\n\n' % (len(allm), KEEP))
            for m in allm:
                f.write(fmt(m) + '\n')
        total_new += len(new)
        merged.extend(allm)
        log('群 %s：新增 %d 条，档案共 %d 条' % (gid, len(new), len(allm)))
    if merged:
        merged.sort(key=lambda m: (int(m.get('ts') or 0)))
        merged = merged[-800:]
        with open(os.path.join(HIST, 'all.md'), 'w', encoding='utf-8') as f:
            f.write('# 所有群的聊天档案（按时间合并）\n')
            f.write('> 每 5 分钟自动更新。共 %d 条。\n\n' % len(merged))
            for m in merged:
                f.write(fmt(m) + '\n')
    log('本轮新增 %d 条' % total_new)
    return total_new


if __name__ == '__main__':
    n = main()
    print('新增 %d 条' % n)
