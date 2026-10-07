# -*- coding: utf-8 -*-
"""人设 / 多角色 / 提示词模板。
提示词放在 prompts/<角色>/ 下的 .md（可直接编辑 ✓）。"""
import os, io, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDIR = os.path.join(ROOT, "prompts")
STATE = os.path.join(ROOT, "data", "persona.json")

DEFAULTS = {
    "system.md": "# 身份\n你是谁、你的性格底色、硬规则。\n",
    "style.md": "# 风格\n怎么说话（长短、口癖、禁用标点）。\n",
    "master.md": "# 对主人\n只在跟主人说话时附加。\n",
}


def ensure(name="default"):
    d = os.path.join(PDIR, name)
    os.makedirs(d, exist_ok=True)
    for f, t in DEFAULTS.items():
        p = os.path.join(d, f)
        if not os.path.exists(p):
            io.open(p, "w", encoding="utf-8").write(t)
    return d


def active():
    try:
        return json.load(io.open(STATE, encoding="utf-8")).get("active") or "default"
    except Exception:
        return "default"


def switch(name):
    ensure(name)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"active": name}, io.open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    return name


def _read(path):
    try:
        return io.open(path, encoding="utf-8").read().strip()
    except Exception:
        return ""


def system_prompt(name=None):
    ensure(name or active())
    return _read(os.path.join(PDIR, name or active(), "system.md"))


def style_prompt(name=None):
    ensure(name or active())
    return _read(os.path.join(PDIR, name or active(), "style.md"))


def master_prompt(name=None):
    ensure(name or active())
    return _read(os.path.join(PDIR, name or active(), "master.md"))


def build(who_is_master=False, extra="", name=None):
    """拼出这一轮的系统提示词"""
    parts = [system_prompt(name), style_prompt(name)]
    if who_is_master:
        parts.append(master_prompt(name))
    if extra:
        parts.append(extra)
    return "\n\n".join([p for p in parts if p])


def list_personas():
    ensure()
    try:
        return [d for d in os.listdir(PDIR) if os.path.isdir(os.path.join(PDIR, d))]
    except Exception:
        return ["default"]
