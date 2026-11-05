# -*- coding: utf-8 -*-
"""补丁原语：每次改动都必须精确命中预期次数，否则立刻失败。

为什么不做「尽力而为」的替换：
补丁是照着某一版上游写的，上游一改就可能静默失效。静默失效的后果比构建失败
严重得多 —— 会产出一个「看起来正常、实际功能还在」的包。断言把静默失效变成
构建失败，红色 X 比错版包便宜。

所有原语在失败时抛 PatchError，异常消息里带文件、期望次数、实际次数，
以及（文本替换时）old 的前 120 个字符，方便直接定位。

── 行尾 ────────────────────────────────────────────────────
上游仓库存的是 LF，但 Windows 上 `core.autocrlf=true` 会检出成 CRLF。
本地测补丁与 CI（Linux，LF）必须看到同一份文本，否则补丁在本地过、在 CI 挂。
所以这里统一在**读入时**把 CRLF 归一成 LF，写回时也一律写 LF ——
CI 本来就是这个形态，本地多出来的 CRLF 只是检出噪声。
"""

import io
import os
import re
import shutil


class PatchError(RuntimeError):
    pass


def read(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    return text.replace("\r\n", "\n")


def write(path, text):
    """一律写 LF（与仓库里的存储形态、与 CI 的检出形态一致）。"""
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\r\n", "\n"))


def _brief(text, n=120):
    flat = text.replace("\n", "\\n")
    return flat if len(flat) <= n else flat[:n] + "…"


def must_replace(path, old, new, count=1, label=None):
    """把 old 换成 new，要求 old 恰好出现 count 次。"""
    if not os.path.isfile(path):
        raise PatchError("目标文件不存在：%s" % path)
    text = read(path)
    got = text.count(old)
    if got != count:
        raise PatchError(
            "%s\n  期望 %d 次，实际 %d 次\n  找不到的原文：%s"
            % (label or path, count, got, _brief(old))
        )
    write(path, text.replace(old, new))
    return got


def must_replace_re(path, pattern, repl, count=1, label=None, flags=0):
    """正则版替换，同样要求命中次数精确。"""
    if not os.path.isfile(path):
        raise PatchError("目标文件不存在：%s" % path)
    text = read(path)
    new_text, got = re.subn(pattern, repl, text, flags=flags)
    if got != count:
        raise PatchError(
            "%s\n  期望 %d 次，实际 %d 次\n  正则：%s"
            % (label or path, count, got, pattern)
        )
    write(path, new_text)
    return got


def must_absent(path, needle, label=None):
    """确认某段文字已经不在文件里（改完之后自检用）。"""
    if not os.path.isfile(path):
        raise PatchError("目标文件不存在：%s" % path)
    if needle in read(path):
        raise PatchError("%s\n  改完后仍然存在：%s" % (label or path, _brief(needle)))


def must_present(path, needle, label=None):
    """确认某段文字确实在文件里（用来确认遗漏的活代码还在）。"""
    if not os.path.isfile(path):
        raise PatchError("目标文件不存在：%s" % path)
    if needle not in read(path):
        raise PatchError("%s\n  应有的内容不存在：%s" % (label or path, _brief(needle)))


def must_delete_file(path):
    if not os.path.isfile(path):
        raise PatchError("要删的文件不存在：%s" % path)
    os.remove(path)


def must_delete_tree(path):
    if not os.path.isdir(path):
        raise PatchError("要删的目录不存在：%s" % path)
    shutil.rmtree(path)


def must_cut_range(
    path, start_marker, end_marker, label=None, expect_start=1, include_end=True, tail=0
):
    """删掉从 start_marker 所在行到 end_marker 所在行之间的内容。

    用来替代「按行号删」—— 行号在上游小改后必然漂移，标记不会。
    结束标记**总是**从 start 的下一行开始找，避免把 start 自己当成结束。

    `include_end` 决定结束标记那一行删不删（默认删）。传 False 时保留它，
    用于「删到某行之前为止」的场景。

    `tail` 是「结束标记之后还要连带删几行」：删一个函数体时，结束标记往往落在
    函数体的最后一条语句上，紧跟的收尾大括号不在标记里 —— 漏删就留下一个多余的
    右大括号，编译器报 unexpected closing delimiter。这种收尾行本身没有独特文本
    可当锚点，只能按「相对结束标记的偏移」删。
    """
    if not os.path.isfile(path):
        raise PatchError("目标文件不存在：%s" % path)
    lines = read(path).split("\n")

    starts = [i for i, ln in enumerate(lines) if start_marker in ln]
    if len(starts) != expect_start:
        raise PatchError(
            "%s\n  起始标记期望 %d 次，实际 %d 次：%s"
            % (label or path, expect_start, len(starts), _brief(start_marker))
        )
    s = starts[0]

    e = None
    for i in range(s + 1, len(lines)):
        if end_marker in lines[i]:
            e = i
            break
    if e is None:
        raise PatchError(
            "%s\n  找不到结束标记：%s" % (label or path, _brief(end_marker))
        )

    last = e if include_end else e - 1
    if last < s:
        raise PatchError(
            "%s\n  结束标记紧贴起始标记，没东西可删：%s"
            % (label or path, _brief(end_marker))
        )

    stop = last + 1 + tail
    if stop > len(lines):
        raise PatchError(
            "%s\n  tail=%d 超出文件末尾（结束标记在第 %d 行，文件共 %d 行）"
            % (label or path, tail, e + 1, len(lines))
        )
    removed = stop - s
    del lines[s:stop]
    write(path, "\n".join(lines))
    return removed


def must_insert_after(path, marker, addition, label=None, expect=1):
    """把 addition 插到 marker 所在行的下一行。"""
    if not os.path.isfile(path):
        raise PatchError("目标文件不存在：%s" % path)
    lines = read(path).split("\n")
    hits = [i for i, ln in enumerate(lines) if marker in ln]
    if len(hits) != expect:
        raise PatchError(
            "%s\n  插入锚点期望 %d 次，实际 %d 次：%s"
            % (label or path, expect, len(hits), _brief(marker))
        )
    i = hits[0]
    lines.insert(i + 1, addition)
    write(path, "\n".join(lines))
    return 1


def section(text, anchor, span=400):
    """取出 anchor 附近的一段，用于生成可读的报错上下文。"""
    i = text.find(anchor)
    if i < 0:
        return ""
    return text[max(0, i - span // 2): i + span]
