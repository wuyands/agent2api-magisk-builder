#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补上游没为 Android 目标做过验证的地方。

## 为什么需要它

上游 `aimod-cc/Agent2API` 的 CI 只编三个桌面平台（windows / macos / linux），
从没编过 `aarch64-linux-android`。个别代码用 `#[cfg(...)]` 按平台分支，
而**桌面三平台的每一支都成立、Android 一支都不成立**，于是类型推断悬空：

    let mut roots = Vec::new();
    #[cfg(windows)]      { roots.push(...); }
    #[cfg(target_os="macos")] { roots.push(...); }
    #[cfg(target_os="linux")] { roots.push(...); }
    // Android 上三条全不成立 → 元素类型推断不出来

这类错误在桌面 CI 里永远撞不出来，编译会直接在 `error[E0282]` 停住。

## 与 `patches/` 的区别

`patches/` 是**功能裁剪**（去掉桌面端专属功能），可以整套关掉；
这里是**编译修补**（只让上游代码在 Android 上能编过，不改行为），
不论打不打裁剪补丁都要跑 —— 所以它在 workflow 里是独立一步。

每条修补都是「精确锚点 + 计数断言 + 幂等」：跑第二遍会说「已修好」，
锚点对不上会直接报错退出（不猜、不尽力而为）。

用法：
    python3 scripts/android-target-fixes.py <上游源码根>
"""

import io
import os
import sys

# 每条： (相对路径, 旧文本, 新文本, 说明)
FIXES = [
    (
        "desktop-tauri/src-tauri/server/src/server/core/plugin_host/wasm"
        "/qoder_umid/discovery.rs",
        "    let mut roots = Vec::new();\n",
        "    let mut roots: Vec<PathBuf> = Vec::new();\n",
        "qoder_umid::roots —— 三个 cfg 分支在 Android 上全不成立，推断不出 Vec 元素类型"
        "（补类型即零行为改动：三种桌面平台 push 进去的都是 PathBuf）",
    ),
]


def read(path):
    return io.open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")


def write(path, text):
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：python3 scripts/android-target-fixes.py <上游源码根>")
    root = sys.argv[1]
    if not os.path.isdir(root):
        sys.exit("✗ 源码根不存在：" + root)

    applied = 0
    skipped = 0
    for rel, old, new, why in FIXES:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            sys.exit("✗ 目标文件不存在：%s\n  （上游改了目录结构？这条修补要重新定位）" % rel)
        text = read(path)
        if new in text:
            print("  --  已修好，跳过：%s" % rel.split("/")[-1])
            skipped += 1
            continue
        count = text.count(old)
        if count != 1:
            sys.exit(
                "✗ 锚点命中 %d 次（期望 1）：%s\n  要改的内容：%r\n  说明：%s"
                % (count, rel, old, why)
            )
        write(path, text.replace(old, new))
        print("  OK  %s" % why)
        applied += 1

    print("Android 目标修补：改了 %d 处，已就绪 %d 处" % (applied, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
