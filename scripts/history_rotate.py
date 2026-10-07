# -*- coding: utf-8 -*-
"""大肥鱼 · 群对话档案【自动分段】
规则：
  · qqbot\history\all.md          = 当前段（永远是最新的 ✓ 她只读这个 ✓）
  · 超过 LIMIT_LINES 行 / LIMIT_MB 兆 → 把 all.md 改名成
        qqbot\history\seg-all-YYYYmmdd-HHMM.md   （旧段 ✓ 永久保留 ✓）
    然后新建一个空的 all.md 继续写 ✓
  · 每个单群档案（YOUR_GROUP_ID.md / YOUR_GROUP_ID2.md …）同样分段 ✓
  · qqbot\history\index.md 里维护一份【所有分段的清单】✓ 方便翻旧账 ✓
用法：python history_rotate.py      （由 archive-history.vbs 每 5 分钟带着跑 ✓）
"""
import io
import os
import time

W = r"C:\Users\28461\Documents\deepseek-harness\default-workspace"
H = os.path.join(W, 'qqbot', 'history')
LIMIT_LINES = 4000          # 超过就分段
LIMIT_MB = 3.0              # 或者超过这个体积
KEEP_DAYS = 0               # 0 = 永不删除（全部留着 ✓）

os.makedirs(H, exist_ok=True)
log = []


def nlines(path):
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def mb(path):
    try:
        return os.path.getsize(path) / 1024.0 / 1024.0
    except Exception:
        return 0.0


def rotate(path):
    """到一个大文件就切成 seg-<名字>-<时间>.md，并让原文件变空"""
    if not os.path.exists(path):
        return None
    ln, size = nlines(path), mb(path)
    if ln < LIMIT_LINES and size < LIMIT_MB:
        return None
    base = os.path.basename(path)[:-3] if path.endswith('.md') else os.path.basename(path)
    stamp = time.strftime('%Y%m%d-%H%M')
    dest = os.path.join(H, 'seg-%s-%s.md' % (base, stamp))
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(H, 'seg-%s-%s-%d.md' % (base, stamp, n))
        n += 1
    try:
        os.replace(path, dest)
    except Exception as e:
        return 'rename failed: %s' % e
    io.open(path, 'w', encoding='utf-8').write('')
    # 记进清单
    idx = os.path.join(H, 'index.md')
    io.open(idx, 'a', encoding='utf-8').write(
        '- %s  %s  (%d 行 / %.1f MB)\n' % (time.strftime('%Y-%m-%d %H:%M'), os.path.basename(dest), ln, size))
    return '%s  (%d 行 / %.1f MB)' % (os.path.basename(dest), ln, size)


# ① 合并档
r = rotate(os.path.join(H, 'all.md'))
if r:
    log.append('all.md -> ' + r)

# ② 各单群档
for f in sorted(os.listdir(H)):
    if not f.endswith('.md'):
        continue
    if f.startswith('seg-') or f in ('all.md', 'index.md'):
        continue
    p = os.path.join(H, f)
    r = rotate(p)
    if r:
        log.append(f + ' -> ' + r)

# ③ 清单头部（第一次建）
idx = os.path.join(H, 'index.md')
if not os.path.exists(idx):
    io.open(idx, 'w', encoding='utf-8').write(
        '# 大肥鱼 \u00b7 \u7fa4\u5bf9\u8bdd\u6863\u6848\u5206\u6bb5\u6e05\u5355\n\n'
        '> \u6700\u65b0\u7684\u6c38\u8fdc\u5728 `all.md` \u2713 \u8fd9\u91cc\u662f\u5386\u53f2\u5206\u6bb5 \u2713\n\n')

print('\n'.join(log) if log else '(no rotation needed)')
print('all.md: %d lines / %.2f MB' % (nlines(os.path.join(H, 'all.md')), mb(os.path.join(H, 'all.md'))))
