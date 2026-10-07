# -*- coding: utf-8 -*-
"""会话体积哨兵：她的群会话涨太大了就【提醒】一次（不硬清 ✗ 免得你老刷新 ✓）
* 因为记忆已经外置在卡片 + memory.md + facts.md 上 ✓ 清会话不再丢记忆 ✓
* 阈值：WARN_MB 提醒（默认 1.5 MB ≈ 40 万 token ✓）
输出：qqbot\memory\session-status.txt（供人和她自己看 ✓）
用法：python session_guard.py
"""
import io
import os
import time

W = r'C:\Users\28461\Documents\deepseek-harness\default-workspace'
SESS = r'C:\Users\28461\.dsh\storages\session_projcache\sessions'
OUT = os.path.join(W, 'qqbot', 'memory', 'session-status.txt')
WARN_MB = 1.5
ALARM_MB = 3.0


def main():
    rows = []
    if os.path.isdir(SESS):
        for f in os.listdir(SESS):
            if not f.startswith('onebot-') or not f.endswith('.json'):
                continue
            p = os.path.join(SESS, f)
            try:
                mb = os.path.getsize(p) / 1024.0 / 1024.0
            except Exception:
                continue
            rows.append((f, mb, time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(p)))))
    rows.sort(key=lambda r: -r[1])
    worst = rows[0][1] if rows else 0.0
    lines = ['# 她的会话体积（越大约容易撞上限）', '', '检查时间：' + time.strftime('%Y-%m-%d %H:%M:%S'), '']
    for f, mb, t in rows[:8]:
        flag = '  ← ★★ 该清了' if mb >= ALARM_MB else ('  ← ★ 注意' if mb >= WARN_MB else '')
        lines.append('- %-48s %6.2f MB   %s%s' % (f[:48], mb, t, flag))
    if worst >= ALARM_MB:
        lines += ['', '★★ 建议：在群里发一次 `/new hard`（记忆不会丢 ✓ 都在卡片和 memory.md 里 ✓）']
    elif worst >= WARN_MB:
        lines += ['', '★ 提示：快满了，找个空闲时候发一次 `/new hard` 就行（不急 ✓）']
    else:
        lines += ['', '✓ 体积正常，什么都不用做']
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines[3:8]))
    print('worst = %.2f MB' % worst)


if __name__ == '__main__':
    main()
