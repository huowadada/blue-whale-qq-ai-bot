# -*- coding: utf-8 -*-
"""平台适配器接口：只管“怎么说话”，不管“说什么”。
新平台（微信/豆瓣/知乎）只需再写一个子类 ✓"""
class Adapter:
    name = "base"
    def capabilities(self): return set()     # {"text","image","voice","video","comment","dm"}
    def poll(self): ...                      # 返回新消息列表（统一结构）
    def send(self, target, text, **kw): ...  # 发消息 / 发评论
    def raw(self, action, **params): ...     # 平台专有能力（如 QQ 的 53 个工具）
