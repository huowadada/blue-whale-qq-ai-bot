# -*- coding: utf-8 -*-
"""\u5927\u80a5\u9c7c \u00b7 \u8bb0\u5fc6\u540c\u6b65
\u628a qqbot\history\all.md \u7684\u6700\u8fd1\u5185\u5bb9\u540c\u6b65\u5230\u3010\u72ec\u7acb\u8bb0\u5fc6\u6587\u6863\u3011
qqbot\memory\memory.md\uff08\u5979\u53ea\u9700\u8981\u8ba4\u8fd9\u4e00\u4e2a\u6587\u4ef6 \u2713\uff09
\u624b\u5199\u8fc7\u7684\u90e8\u5206\uff08\u8eab\u4efd/\u4e3b\u4eba/\u7fa4\u91cc\u7684\u4eba\xb7\u89c4\u77e9/\u5979\u5b66\u5230\u7684\uff09\u4e0d\u4f1a\u88ab\u8986\u76d6 \u2713
"""
import io, os, time

W = r"C:\Users\28461\Documents\deepseek-harness\default-workspace"
H = os.path.join(W, "qqbot", "history")
M = os.path.join(W, "qqbot", "memory", "memory.md")
KEEP_TAIL = 1000          # \u8bb0\u5fc6\u6587\u6863\u91cc\u4fdd\u7559\u591a\u5c11\u884c\u6700\u8fd1\u5bf9\u8bdd


def tail_lines(path, n):
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except Exception:
        return []


def main():
    os.makedirs(os.path.dirname(M), exist_ok=True)
    old = io.open(M, encoding="utf-8").read() if os.path.exists(M) else ""
    # \u4fdd\u7559\u624b\u5199\u90e8\u5206\uff1a\u5230\u300c## \u6700\u8fd1\u4e0a\u4e0b\u6587\u300d\u4e4b\u524d\u7684\u5168\u90e8
    head = old.split("## \u6700\u8fd1\u4e0a\u4e0b\u6587")[0].rstrip()
    if head.strip() == "":
        head = (
            "# \u8d85\u7ea7\u5927\u80a5\u9c7c \u00b7 \u957f\u671f\u8bb0\u5fc6\uff08\u5979\u81ea\u5df1\u770b\u7684\u6587\u6863 \u2713\uff09\n\n"
            "> \u2605 \u8fd9\u662f\u5979\u7684\u3010\u72ec\u7acb\u8bb0\u5fc6\u6587\u6863\u3011\u2713 \u6bcf 5 \u5206\u949f\u81ea\u52a8\u5237\u65b0\u4e0b\u9762\u90a3\u6bb5 \u2713\n"
            "> \u2605 \u4e0a\u9762\u8fd9\u4e9b\u5c0f\u8282\u53ef\u4ee5\u624b\u5199\uff08\u5979\u81ea\u5df1\u4e5f\u80fd\u6539 \u2713\uff09\uff0c\u4e0d\u4f1a\u88ab\u8986\u76d6 \u2713\n\n"
            "## \u8eab\u4efd\n- \u6211\u53eb**\u8d85\u7ea7\u5927\u80a5\u9c7c**\uff08QQ \u6635\u79f0\u84dd\u8272\u5927\u80a5\u9c7c\uff09\uff0cQQ YOUR_BOT_QQ\n"
            "- \u6211\u5728 B\u7ad9\uff08UID YOUR_BILI_UID\uff09\u548c QQ \u7fa4\u91cc\u6d3b\u52a8 \u2713\n\n"
            "## \u4e3b\u4eba\n- **\u706b\u5a03rc**\uff08QQ YOUR_QQ\uff09\u2713 \u4ed6\u8bf4\u4e86\u7b97 \u2713\n\n"
            "## \u7fa4\n- YOUR_GROUP_ID \u00b7 YOUR_GROUP_ID2\uff08\u53ea\u5728\u8fd9\u4e24\u4e2a\u7fa4\u56de\u8bdd \u2713\uff09\n\n"
            "## \u5b66\u5230\u7684\uff08\u5979\u81ea\u5df1\u8865\uff09\n- \uff08\u7a7a\u7740\uff0c\u60f3\u8bb0\u5c31\u5199\u8fd9\u91cc \u2713\uff09\n\n"
            "## \u6700\u8fd1\u4e0a\u4e0b\u6587\n")
    tail = tail_lines(os.path.join(H, "all.md"), KEEP_TAIL)
    # \u53bb\u91cd\u7a7a\u884c
    body = "".join(tail).strip()
    io.open(M, "w", encoding="utf-8").write(
        head + "\n<!-- \u4e0b\u9762\u6bcf 5 \u5206\u949f\u81ea\u52a8\u91cd\u5199 \u2713 \u4e0d\u8981\u624b\u6539 \u2717 -->\n"
        + "_\u6700\u540e\u540c\u6b65\uff1a" + time.strftime("%Y-%m-%d %H:%M:%S") + "_\n\n" + body + "\n")
    return len(body.split("\n"))


if __name__ == "__main__":
    n = main()
    print("\u8bb0\u5fc6\u6587\u6863\u5df2\u540c\u6b65\uff1a%d \u884c" % n)
