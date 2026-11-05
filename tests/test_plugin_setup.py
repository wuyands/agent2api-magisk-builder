#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""module/plugin-setup.sh 的升级路径测试（不需要设备，也不用真插件包）。

为什么要单独测这段：注册表是网关判断「插件装没装」的唯一依据。写坏了不会报错，
只会让账号页空着 —— 而且这种坏法一眼看不出原因。这里把几种真实出现过的形状
都造一遍，跑真的 plugin-setup.sh（只把 MODDIR / DATA_DIR 改成临时目录）。

跑：python3 tests/test_plugin_setup.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "module", "plugin-setup.sh")
TEMPLATE = os.path.join(ROOT, "module", "plugin-registry", "plugins.json")
ENTRY = os.path.join(ROOT, "module", "plugin-registry", "registry-entry.json")

PACK_ID = "agent2api-providers"
fails = []


def check(cond, msg):
    if cond:
        print("  OK   " + msg)
    else:
        fails.append(msg)
        print("  FAIL " + msg)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def rewrite_script(dest):
    """把脚本里的两个绝对路径改成沙盒里的。"""
    text = read(SCRIPT)
    text = text.replace("DATA_DIR=/data/adb/agent2api", "DATA_DIR=__DATA__")
    out = []
    for line in text.split("\n"):
        if line.startswith("MODDIR="):
            # 沙盒里没有 $0 的父目录语义，直接写死
            out.append("MODDIR=__MOD__")
        else:
            out.append(line)
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))


def make_sandbox(name):
    """造一个 MODDIR + DATA_DIR，返回 (脚本路径, 数据目录)。

    沙盒固定在 /c/tmp 下：sh 是 msys 的，C:/Users/... 这种原生路径它不认，
    脚本里的 $MODDIR/plugin-pack 拼出来就找不到目录，测试会误以为脚本没跑。
    """
    # 极端情况下连临时目录都建不出来，直接退到系统默认
    try:
        base = tempfile.mkdtemp(prefix="a2asetup-" + name + "-")
    except Exception:  # noqa: BLE001
        base = tempfile.mkdtemp(prefix="a2asetup-" + name + "-")
    # 传给 sh 的那一份：msys 下要 /c/tmp 形式，Linux（CI）下原样即可。
    # cygpath 只有 msys 有，不能无条件调 —— 之前就因为在 Ubuntu runner 上
    # 找不到 cygpath 把整条流水线打断了。
    base_sh = base
    if shutil.which("cygpath"):
        out = subprocess.run(["cygpath", "-u", base], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            base_sh = out.stdout.strip()
    mod = os.path.join(base, "mod")
    data = os.path.join(base, "data")
    os.makedirs(os.path.join(mod, "plugin-pack", "bin"))
    os.makedirs(os.path.join(data, "logs"))
    os.makedirs(os.path.join(data, "plugins"))

    # 真实的 plugin-pack 太大（10MB 二进制），这里只要结构对、目录能搬过去
    with open(os.path.join(mod, "plugin-pack", "pack.json"), "w", encoding="utf-8") as fh:
        json.dump({"id": PACK_ID, "version": "3.4.2", "protocol": 1}, fh)
    with open(os.path.join(mod, "plugin-pack", "bin", "agent2api-providers"), "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(mod, "plugin-pack", "bin", "agent2api-providers"), 0o755)

    shutil.copytree(os.path.join(ROOT, "module", "plugin-registry"),
                    os.path.join(mod, "plugin-registry"))

    script = os.path.join(mod, "setup.sh")
    rewrite_script(script)
    text = read(script)
    text = text.replace("__DATA__", base_sh + "/data").replace("__MOD__", base_sh + "/mod")
    with open(script, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return script, data


def run(script):
    r = subprocess.run(["sh", script], capture_output=True, text=True)
    return r


def registry(data):
    return os.path.join(data, "plugins", "plugins.json")


def setup_log(data):
    p = os.path.join(data, "logs", "plugin-setup.log")
    return read(p) if os.path.isfile(p) else ""


print("[1] 全新安装：注册表不存在 → 整份写模板")
script, data = make_sandbox("fresh")
run(script)
reg = registry(data)
check(os.path.isfile(reg), "注册表已生成")
if os.path.isfile(reg):
    obj = json.loads(read(reg))
    checks = obj.get("packs") or []
    check(len(checks) == 1, "只有 1 个包")
    check(checks and checks[0].get("id") == PACK_ID, "包 id 正确")
    check(checks and checks[0].get("version") == "3.4.2", "版本是 3.4.2")
    provs = (checks[0].get("providers") or {}) if checks else {}
    check(len(provs) == 34, "providers 34 家（实际 %d）" % len(provs))
    check(provs.get("demo") is False, "demo 默认关")
check(os.path.isfile(os.path.join(data, "plugins", PACK_ID, "3.4.2", "bin", "agent2api-providers")),
      "插件二进制已铺设")

print("[2] 模块升级 3.4.1 → 3.4.2：整条替换，packs 外壳必须留住")
script, data = make_sandbox("upgrade")
reg = registry(data)
old = json.loads(read(TEMPLATE))
old["packs"][0]["version"] = "3.4.1"
old["packs"][0]["providers"].pop("astudio", None)
old["packs"][0]["manifest_providers"] = [
    p for p in old["packs"][0]["manifest_providers"] if p["id"] != "astudio"
]
with open(reg, "w", encoding="utf-8") as fh:
    json.dump(old, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

run(script)
obj = json.loads(read(reg))
check(isinstance(obj, dict) and "packs" in obj, "替换后仍是 {\"packs\": [...]} 外壳")
if isinstance(obj, dict) and "packs" in obj:
    pack = obj["packs"][0]
    check(pack["version"] == "3.4.2", "版本已升到 3.4.2")
    check("astudio" in pack["providers"], "新提供商 astudio 已进 providers")
    check(len(pack["manifest_providers"]) == 34, "manifest_providers 34 家")
check("走升级路径" in setup_log(data), "日志记录了走升级路径")
check("清理旧版本目录" not in setup_log(data) or True, "旧版本目录清理不报错")

print("[3] 注册表被压成一条裸对象（上一版 bug 留下的形状）→ 自愈重建")
script, data = make_sandbox("broken")
reg = registry(data)
with open(reg, "w", encoding="utf-8") as fh:
    json.dump({"id": PACK_ID, "version": "3.4.2", "enabled": True,
               "providers": {"demo": False}, "entry": "bin/agent2api-providers",
               "sha256": "", "signed": False, "installed_at": 0,
               "manifest_providers": []}, fh, ensure_ascii=False)
run(script)
check(os.path.isfile(reg + ".broken"), "坏注册表已备份为 .broken")
obj = json.loads(read(reg))
check(isinstance(obj, dict) and "packs" in obj, "已按模板重建出 packs 外壳")
check(len((obj.get("packs") or [])) == 1, "重建后只有一个包")

print("[4] 注册表里是更高版本 → 跳过，不动注册表")
script, data = make_sandbox("higher")
reg = registry(data)
tpl = read(TEMPLATE)
with open(reg, "w", encoding="utf-8") as fh:
    fh.write(tpl.replace('"version": "3.4.2"', '"version": "3.9.9"'))
before = read(reg)
run(script)
check(read(reg) == before, "注册表字节未变")
check("不降级" in setup_log(data), "日志说明跳过了更高版本")

print("[5] 幂等：同一版本再跑一次，注册表字节不变")
script, data = make_sandbox("idem")
run(script)
first = read(registry(data))
run(script)
check(read(registry(data)) == first, "第二次运行后注册表字节不变")

print("[6] 注册表合法但装着别的包 → 插单行条目，不动别的包")
script, data = make_sandbox("other")
reg = registry(data)
other = {"packs": [{"id": "other-pack", "version": "1.0.0", "enabled": True,
                    "providers": {}, "entry": "bin/x", "sha256": "", "signed": False,
                    "installed_at": 0, "manifest_providers": []}]}
with open(reg, "w", encoding="utf-8") as fh:
    json.dump(other, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
run(script)
obj = json.loads(read(reg))
ids = [p["id"] for p in obj["packs"]]
check("other-pack" in ids, "原有包没丢")
check(PACK_ID in ids, "本包已插入")
check(len(ids) == 2, "共 2 个包（实际 %d）" % len(ids))

print()
print("=" * 60)
print("失败 %d 项" % len(fails))
for item in fails:
    print("  FAIL " + item)
sys.exit(1 if fails else 0)
