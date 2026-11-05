#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成模块清单：module.prop 的版本字段 + plugin-pack/pack.json + plugin-registry/*.json。

这一步把「版本号」这件事收成一个地方：CI 只传一个 `--version v3.4.2`，
剩下三处（module.prop 的 version/versionCode、插件包的 version、注册表的
version）全部由这里统一写，避免出现「模块说 3.4.2、注册表说 3.4.1」这种
自相矛盾的包。

用法：
    python scripts/prepare.py --version v3.4.2 --plugin-version 3.4.2 \
        --server-bin out/agent2api-server \
        --providers-bin out/agent2api-providers \
        --ui-ui out/ui \
        --plugin-src build/px

`--plugin-src` 指向插件仓库的检出目录（里面应有 pack.json / ui/ / assets/）。
"""

import argparse
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "module")
PACK_DIR = os.path.join(MODULE, "plugin-pack")
REG_DIR = os.path.join(MODULE, "plugin-registry")

# 网关在 Android 上会解析的 target triple（见 core/plugin_host/rpc.rs 的
# `target_triple()`：非 Windows / macOS 一律回落 `<arch>-unknown-linux-gnu`）。
ANDROID_TRIPLE = "aarch64-unknown-linux-gnu"


def die(msg):
    sys.stderr.write("✗ " + msg + "\n")
    sys.exit(1)


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(path, obj, indent=None, separators=None, trailing_newline=True):
    text = json.dumps(obj, ensure_ascii=False, indent=indent, separators=separators)
    write_text(path, text + ("\n" if trailing_newline else ""))


def code_of(version):
    """v3.4.2 → 3040200。规则：major*1000000 + minor*10000 + patch*100。

    Magisk 只用它比大小，所以要求「段位越高数越大」且**永不撞车**。
    早期移植用的是 major*10000 + minor*1000 + patch*100（3.4.2→34200），
    但那个规则在 minor 到两位数时会撞：3.10.7 与 4.0.7 都算出 40700。
    上游现在还在 3.x，可这套东西是要长期跟着上游跑的，把位宽一次留够：
    minor 与 patch 各两位，major 不设上限。
    """
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if not m:
        die("看不懂的版本号：%r（要形如 v3.4.2）" % version)
    major, minor, patch = (int(x) for x in m.groups())
    if minor > 99 or patch > 99:
        die("版本号超出映射位宽（minor / patch 需 ≤ 99）：%s" % version)
    return major * 1000000 + minor * 10000 + patch * 100


def bump_module_prop(version):
    path = os.path.join(MODULE, "module.prop")
    text = read_text(path)
    code = code_of(version)
    text = re.sub(r"(?m)^version=.*$", "version=" + version, text)
    text = re.sub(r"(?m)^versionCode=.*$", "versionCode=%d" % code, text)
    write_text(path, text)
    return code


def copy_tree(src, dst):
    if not os.path.isdir(src):
        die("目录不存在：" + src)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return sum(len(files) for _, _, files in os.walk(dst))


def copy_file(src, dst):
    if not os.path.isfile(src):
        die("文件不存在：" + src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o755)
    return os.path.getsize(dst)


def build_pack_json(plugin_src, plugin_version):
    """把插件仓库的 pack.json 改写成「只认 Android 一份」的版本。

    上游的 `entry` 列了五个平台；手机上永远只会命中
    `aarch64-unknown-linux-gnu` 那一条，留着另外四条只会在出问题时误导人
    （「明明有 x86_64 的条目为什么说找不到」）。所以这里只保留命中的那条。
    """
    src = os.path.join(plugin_src, "pack.json")
    if not os.path.isfile(src):
        die("插件仓库里没有 pack.json：" + src)
    # 上游这个文件带 BOM，json 模块读 utf-8-sig 才不报错
    with open(src, "r", encoding="utf-8-sig") as fh:
        pack = json.load(fh)

    original_version = pack.get("version")
    if original_version != plugin_version:
        sys.stderr.write(
            "! 插件仓库 pack.json 自报 version=%s，与 --plugin-version=%s 不一致"
            "（以 CLI 为准写进包里）\n" % (original_version, plugin_version)
        )
    pack["version"] = plugin_version

    entry = pack.get("entry") or {}
    if ANDROID_TRIPLE not in entry:
        die("插件 pack.json 的 entry 里没有 %s，这个插件包无法在手机上运行" % ANDROID_TRIPLE)
    pack["entry"] = {ANDROID_TRIPLE: entry[ANDROID_TRIPLE]}

    write_json(os.path.join(PACK_DIR, "pack.json"), pack, indent=2)
    return pack


def build_registry(pack):
    """按 pack.json 现生成注册表两份文件（模板 + 单行条目）。

    `plugins.json` 是「首次启动时的整份模板」：模块第一次装到手机上、
    `/data/adb/agent2api/plugins/plugins.json` 还不存在时由 plugin-setup.sh
    原样拷过去。`registry-entry.json` 是「注册表已存在但还没有本包」时插进去
    的那一条。两者的 provider 布尔表必须与 pack.json 完全一致 —— 否则新装/升级
    之后，那些在 pack.json 里读不到清单的路径会回落到旧集合，新提供商就消失了。
    """
    providers = pack.get("providers") or []
    if not providers:
        die("pack.json 里没有 providers 列表")

    flags = {p["id"]: bool(p.get("default_enabled", True)) for p in providers}
    manifest = [
        {
            "id": p["id"],
            "label": p["label"],
            "order": p.get("order", 0),
            "default_enabled": bool(p.get("default_enabled", True)),
        }
        for p in providers
    ]

    entry = {
        "id": pack["id"],
        "version": pack["version"],
        "enabled": True,
        "providers": flags,
        "entry": "bin/agent2api-providers",
        "sha256": "",
        "signed": False,
        "installed_at": 0,
        "manifest_providers": manifest,
    }

    template = {"packs": [dict(entry)]}
    write_json(os.path.join(REG_DIR, "plugins.json"), template, indent=2)
    write_json(
        os.path.join(REG_DIR, "registry-entry.json"),
        entry,
        separators=(",", ":"),
    )
    return len(providers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="模块版本，形如 v3.4.2")
    ap.add_argument("--plugin-version", required=True, help="插件包版本，形如 3.4.2")
    ap.add_argument("--server-bin", required=True, help="编好的 agent2api-server（aarch64 ELF）")
    ap.add_argument("--providers-bin", required=True, help="编好的 agent2api-providers（aarch64 ELF）")
    ap.add_argument("--ui-ui", required=True, help="网关前端产物目录（含 app.js / islands/ui.js）")
    ap.add_argument("--plugin-src", required=True, help="插件仓库检出目录")
    args = ap.parse_args()

    code = bump_module_prop(args.version)
    print("  module.prop        version=%s versionCode=%d" % (args.version, code))

    pack = build_pack_json(args.plugin_src, args.plugin_version)
    print("  plugin-pack/pack.json  version=%s providers=%d entry=%s"
          % (pack["version"], len(pack.get("providers") or []), ANDROID_TRIPLE))

    n = build_registry(pack)
    print("  plugin-registry    2 份（%d 个 provider）" % n)

    # 插件自带的 11 个面板文件 + 15 张图标
    ui_n = copy_tree(os.path.join(args.plugin_src, "ui"), os.path.join(PACK_DIR, "ui"))
    assets_n = copy_tree(os.path.join(args.plugin_src, "assets"), os.path.join(PACK_DIR, "assets"))
    print("  plugin-pack/ui     %d 个文件" % ui_n)
    print("  plugin-pack/assets %d 个文件" % assets_n)

    s1 = copy_file(args.server_bin, os.path.join(MODULE, "bin", "agent2api-server"))
    s2 = copy_file(args.providers_bin, os.path.join(PACK_DIR, "bin", "agent2api-providers"))
    print("  bin/agent2api-server            %d 字节" % s1)
    print("  plugin-pack/bin/agent2api-providers %d 字节" % s2)

    ui_n = copy_tree(args.ui_ui, os.path.join(MODULE, "ui"))
    print("  ui/                %d 个文件" % ui_n)

    # 脚本里的插件版本号（plugin-setup.sh 的 PACK_VER 与 customize.sh 的提示语）
    setup = os.path.join(MODULE, "plugin-setup.sh")
    text = read_text(setup)
    text = re.sub(r"(?m)^PACK_VER=.*$", "PACK_VER=" + args.plugin_version, text)
    write_text(setup, text)

    cust = os.path.join(MODULE, "customize.sh")
    text = read_text(cust)
    text = re.sub(
        r"(?m)^(\s*ui_print \"- 已内置提供商插件 v)[0-9][0-9.]*(（首次启动自动铺设，)[0-9]+( 家实现）\")$",
        r"\g<1>%s\g<2>%d\g<3>" % (args.plugin_version, len(pack.get("providers") or [])),
        text,
    )
    write_text(cust, text)
    print("  plugin-setup.sh / customize.sh  版本串已同步")


if __name__ == "__main__":
    main()
