#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补丁引擎与清单生成的单元测试（不需要上游源码，秒级跑完）。

跑：python3 tests/test_patches.py

这几类东西错了会让「构建成功但包是坏的」，所以必须有测试兜住：
  · 补丁原语的计数语义（少删一处 = 功能还在；多删一处 = 编译不过）
  · 行尾归一（本地 CRLF 与 CI 的 LF 必须看到同一份文本）
  · versionCode 的映射（错了 Magisk 判断不出升级）
  · 补丁清单本身（每个都要求有 TITLE / apply，顺序稳定）
"""

import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "patches"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import base  # noqa: E402
import prepare  # noqa: E402
import apply as engine  # noqa: E402

fails = []


def check(cond, msg):
    if cond:
        print("  OK   " + msg)
    else:
        fails.append(msg)
        print("  FAIL " + msg)


def tmpfile(text):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def expect_error(fn, needle, msg):
    try:
        fn()
    except base.PatchError as exc:
        check(needle in str(exc), "%s（报错含「%s」）" % (msg, needle))
    except Exception as exc:  # noqa: BLE001
        check(False, msg + "（抛了非 PatchError：%r）" % exc)
    else:
        check(False, msg + "（居然没抛错）")


print("[1] must_replace 的计数语义")
p = tmpfile("aaa\nbbb\nccc\n")
base.must_replace(p, "bbb", "BBB")
check(base.read(p) == "aaa\nBBB\nccc\n", "唯一命中时正常替换")

p = tmpfile("aaa\nbbb\naaa\n")
expect_error(lambda: base.must_replace(p, "aaa", "XXX"),
             "期望 1 次，实际 2 次", "重复命中时拒绝（不猜要改哪个）")
check(base.read(p) == "aaa\nbbb\naaa\n", "失败时文件没被改动")

p = tmpfile("aaa\n")
expect_error(lambda: base.must_replace(p, "zzz", "x"),
             "期望 1 次，实际 0 次", "上游删掉那段代码时明确报错")

p = tmpfile("aaa\naaa\n")
base.must_replace(p, "aaa", "b", count=2)
check(base.read(p) == "b\nb\n", "count=2 时两处都改")

print("[2] 行尾归一：本地 CRLF / CI LF 必须等价")
p = tmpfile("line1\r\nline2\r\n")
check(base.read(p) == "line1\nline2\n", "读入时 CRLF → LF")
base.must_replace(p, "line2", "LINE2")
with io.open(p, "rb") as fh:
    raw = fh.read()
check(b"\r" not in raw, "写出的一律是 LF")
check(raw == b"line1\nLINE2\n", "CRLF 输入也能命中")

print("[3] must_cut_range 的边界")
p = tmpfile("head\nSTART\nmid1\nmid2\nEND\ntail\n")
base.must_cut_range(p, "START", "END")
check(base.read(p) == "head\ntail\n", "默认删到结束标记那一行为止")

p = tmpfile("head\nSTART\nmid\nEND\n})x;\n}\n\ntail\n")
base.must_cut_range(p, "START", "END", tail=3)
check(base.read(p) == "head\ntail\n", "tail=3 连带删掉结束标记之后的 3 行（收尾大括号那类）")

p = tmpfile("A\nB\nC\n")
base.must_cut_range(p, "A", "B", include_end=False)
check(base.read(p) == "B\nC\n", "include_end=False 保留结束标记那一行")

p = tmpfile("A\nB\nC\n")
expect_error(lambda: base.must_cut_range(p, "A", "ZZZ"),
             "找不到结束标记", "结束标记缺失时明确报错")

p = tmpfile("A\nB\n")
expect_error(lambda: base.must_cut_range(p, "A", "B", tail=9),
             "超出", "tail 越过文件尾时明确报错")

print("[4] 删文件 / 存在性断言")
d = tempfile.mkdtemp()
f = os.path.join(d, "gone.txt")
with io.open(f, "w", encoding="utf-8") as fh:
    fh.write("x")
base.must_delete_file(f)
check(not os.path.exists(f), "文件已删")
expect_error(lambda: base.must_delete_file(f),
             "不存在", "重复删同一个文件要报错（说明在重跑）")

p = tmpfile("hello world\n")
base.must_absent(p, "goodbye")
check(True, "must_absent：真的没有就通过")
expect_error(lambda: base.must_absent(p, "hello"), "仍然存在", "must_absent：还在就报错")
base.must_present(p, "hello")
check(True, "must_present：有就通过")
expect_error(lambda: base.must_present(p, "nope"), "不存在", "must_present：没有就报错")

print("[5] versionCode 映射")
for version, want in (
    ("v3.4.2", 3040200),
    ("v3.4.1", 3040100),
    ("v3.4.0", 3040000),
    ("v3.1.0", 3010000),
    ("3.4.2", 3040200),
    ("v4.0.0", 4000000),
    ("v3.10.7", 3100700),
    ("v4.0.7", 4000700),
):
    got = prepare.code_of(version)
    check(got == want, "%s → %d" % (version, want))

# 旧规则 major*1e4+minor*1e3+patch*1e2 会让 3.10.7 与 4.0.7 撞成同一个数；
# 现规则必须让它们严格不同，且「版本更高 → 数更大」在整个 3.x / 4.x 区间成立。
check(prepare.code_of("v3.10.7") != prepare.code_of("v4.0.7"), "3.10.7 与 4.0.7 不再撞车")
ordered = ["v3.4.2", "v3.9.9", "v3.10.0", "v3.10.7", "v4.0.0", "v4.0.7"]
codes = [prepare.code_of(v) for v in ordered]
check(codes == sorted(codes) and len(set(codes)) == len(codes),
      "递增序列的 versionCode 严格单调：%s" % codes)

check(prepare.code_of("v3.4.2") == __import__("verify").code_of("v3.4.2"),
      "verify.py 与 prepare.py 用的是同一套映射")

print("[6] 补丁清单")
for group in engine.GROUPS:
    mods = engine.collect(group)
    check(len(mods) > 0, "%s 组收集到 %d 个补丁" % (group, len(mods)))
    for name, module in mods:
        check(bool(getattr(module, "TITLE", "")), "%s 有 TITLE" % name)
        check(callable(getattr(module, "apply", None)), "%s 有 apply()" % name)

names_rust = [n for n, _ in engine.collect("rust")]
check(names_rust == sorted(names_rust), "rust 组按文件名排序（%d 个）" % len(names_rust))
names_fe = [n for n, _ in engine.collect("frontend")]
check(names_fe == sorted(names_fe), "frontend 组按文件名排序（%d 个）" % len(names_fe))

# 只跑某一组时不能把另一组也捡进来
check([n for n, _ in engine.collect("rust", only="frontend")] == [],
      "--only frontend 时不收集 rust")

print()
print("=" * 60)
print("失败 %d 项" % len(fails))
for item in fails:
    print("  FAIL " + item)
sys.exit(1 if fails else 0)
