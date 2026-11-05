# -*- coding: utf-8 -*-
"""Android 适配裁剪总入口。

用法：
    python patches/apply.py <上游源码根>          # 应用全部补丁
    python patches/apply.py <上游源码根> --list   # 只列出会做什么
    python patches/apply.py <上游源码根> --only rust  # 只跑某一类

补丁按文件名排序执行。任何一个断言失败都会立刻中断并打印定位信息 ——
这是刻意的：静默失效会产出一个「看起来正常、功能还在」的包，比构建失败糟糕得多。
"""

import importlib
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from base import PatchError  # noqa: E402

GROUPS = ["rust", "frontend"]


def collect(group, only=None):
    """按文件名排序收集某组补丁模块。"""
    if only and only != group:
        return []
    folder = os.path.join(HERE, group)
    if not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        mod_name = "%s.%s" % (group, name[:-3])
        out.append((mod_name, importlib.import_module(mod_name)))
    return out


def main(argv):
    if len(argv) < 2:
        print("用法：apply.py <上游源码根> [--list] [--only rust|frontend]")
        return 2

    root = os.path.abspath(argv[1])
    if not os.path.isdir(root):
        print("源码根不存在：%s" % root)
        return 2

    listing = "--list" in argv
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]

    plan = []
    for group in GROUPS:
        for mod_name, module in collect(group, only):
            enabled = getattr(module, "ENABLED", True)
            plan.append((mod_name, module, enabled))

    if listing:
        for mod_name, module, enabled in plan:
            mark = "+" if enabled else "-"
            print("%s %-46s %s" % (mark, mod_name, getattr(module, "TITLE", "")))
        return 0

    applied = 0
    skipped = 0
    for mod_name, module, enabled in plan:
        if not enabled:
            print("  跳过 %-44s %s" % (mod_name, getattr(module, "TITLE", "")))
            skipped += 1
            continue
        title = getattr(module, "TITLE", "")
        try:
            detail = module.apply(root)
        except PatchError as error:
            print("\n❌ 补丁失败：%s  (%s)" % (mod_name, title))
            print(str(error))
            print("\n这一版上游改动了补丁依赖的代码。请按上面的定位信息更新 %s.py。" % mod_name)
            return 1
        except Exception:
            print("\n❌ 补丁异常：%s  (%s)" % (mod_name, title))
            traceback.print_exc()
            return 1
        applied += 1
        print("  ✅ %-44s %-30s %s" % (mod_name, title, detail or ""))

    print("\n完成：应用 %d 个，跳过 %d 个。" % (applied, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
