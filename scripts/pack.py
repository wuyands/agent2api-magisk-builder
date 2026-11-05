#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 module/ 打成 Magisk 模块 zip。

Magisk 的安装器（update-binary）会按条目解包并保留权限位，所以这里必须显式
写 external_attr —— 用 shutil/zipfile 的默认值打出来的脚本会丢掉 +x，装到手机上
service.sh 就跑不起来。

时间戳固定：同一份源码反复打包得到同一个 zip（sha256 一致），这样「模块商店里
这一版是不是同一版」可以直接比哈希，也让 release 资产可复现。

用法：
    python scripts/pack.py --out out/agent2api-magisk-v3.4.2.zip
"""

import argparse
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "module")

# 必须可执行的那些（其余一律 0644）
EXEC = {
    "bin/agent2api-server",
    "plugin-pack/bin/agent2api-providers",
    "service.sh",
    "watchdog.sh",
    "plugin-setup.sh",
    "ctl.sh",
    "uninstall.sh",
    "action.sh",
    "customize.sh",
    "META-INF/com/google/android/update-binary",
}

# 固定时间戳：2026-01-01 00:00:00（zip 的最小可表示年份是 1980）
DATE_TIME = (2026, 1, 1, 0, 0, 0)


def sort_key(rel):
    # META-INF 排最前：部分安装器先读它再决定怎么解包
    return (0 if rel.startswith("META-INF/") else 1, rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出 zip 路径")
    ap.add_argument("--module", default=MODULE, help="模块目录（默认仓库里的 module/）")
    args = ap.parse_args()

    src = args.module
    if not os.path.isdir(src):
        sys.exit("✗ 模块目录不存在：" + src)

    rows = []
    for root, dirs, files in os.walk(src):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, src).replace("\\", "/")
            rows.append((rel, full))
    rows.sort(key=lambda r: sort_key(r[0]))

    missing = sorted(EXEC - {rel for rel, _ in rows})
    if missing:
        sys.exit("✗ 缺必备文件：" + ", ".join(missing))

    out = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    raw_total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, full in rows:
            info = zipfile.ZipInfo(rel, date_time=DATE_TIME)
            info.external_attr = (0o100755 if rel in EXEC else 0o100644) << 16
            info.create_system = 0  # 0 = MS-DOS/FAT，安卓解包器不会去翻译 unix 元数据
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as fh:
                data = fh.read()
            z.writestr(info, data)
            raw_total += len(data)

    with open(out, "rb") as fh:
        blob = fh.read()
    print("  %d 个条目，原始 %.2f MB → %s（%.2f MB）"
          % (len(rows), raw_total / 1048576.0, out, len(blob) / 1048576.0))
    print("  md5    " + hashlib.md5(blob).hexdigest())
    print("  sha256 " + hashlib.sha256(blob).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
