#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 zip 自检：解压后逐项核对，任何一项不过就以非 0 退出。

这个脚本是 CI 的最后一道闸门。它不复述构建过程，只对着**打好的 zip** 检查
「一个陌生手机上装进去会发生什么」：

  1. 该在的文件都在（少一个就白装）
  2. module.prop 的版本对得上，中文没被写成替换字符
  3. 三处版本号（module.prop / plugin-setup.sh / pack.json / 注册表）互相一致
  4. 两个二进制确实是 Android aarch64，且内嵌版本是这一版
  5. 前端产物存在、语法可解析、被裁功能的入口真的没了
  6. 被裁功能的后端路由没有以字符串形式留在任何 .rs 里
  7. shell 脚本 `sh -n` 全过（mksh/toybox 的语法子集）
  8. 所有 JSON 能严格解析（注册表解析失败会让网关把所有账号静默隐藏）
  9. zip 权限位正确、能通过 CRC 校验

用法：
    python scripts/verify.py --zip out/agent2api-magisk-v3.4.2.zip \
        --version v3.4.2 --plugin-version 3.4.2 [--source build/up]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

fails = []
warns = []

REQUIRED = [
    "module.prop", "service.sh", "watchdog.sh", "ctl.sh", "uninstall.sh",
    "action.sh", "customize.sh", "plugin-setup.sh", "LICENSE",
    "bin/agent2api-server",
    "plugin-pack/pack.json",
    "plugin-pack/bin/agent2api-providers",
    "plugin-registry/plugins.json",
    "plugin-registry/registry-entry.json",
    "ui/index.html",
    "ui/app.js",
    "ui/sidebar-layout.js",
    "ui/islands/ui.js",
    "ui/islands/ui.css",
    "webroot/index.html",
    "META-INF/com/google/android/update-binary",
    "META-INF/com/google/android/updater-script",
]

SHELLS = [
    "service.sh", "watchdog.sh", "ctl.sh", "uninstall.sh", "action.sh",
    "customize.sh", "plugin-setup.sh",
    "META-INF/com/google/android/update-binary",
]

EXEC = {
    "bin/agent2api-server",
    "plugin-pack/bin/agent2api-providers",
    "service.sh", "watchdog.sh", "plugin-setup.sh", "ctl.sh",
    "uninstall.sh", "action.sh", "customize.sh",
    "META-INF/com/google/android/update-binary",
}

# 被裁功能在产物里不该再出现的入口标记
UI_ABSENT = [
    ('oa("agent"', "Agent 页注册"),
    ('"data-cat":"about"', "设置页「更新」分类"),
    ("nav-count-update", "导航上的更新角标"),
    ("本机接入", "工具服务「本机接入」列"),
    ("客户端环境", "工具服务「客户端环境」按钮"),
    ("/api/agents", "Agent 接口"),
    ("/api/update/", "软件更新接口"),
    ("/api/import/cc-switch", "cc-switch 导入接口"),
]

# 被裁的后端路由（不应以字面量形式留在任何 .rs 里）
ROUTE_PAT = re.compile(
    r'"(/api/(?:agents|update|import/cc-switch)[^"]*'
    r'|/api/tools/(?:install-targets|install-skill|install-mcp|uninstall-skill'
    r'|uninstall-mcp|mcp-bridge)[^"]*)"'
)


def ok(msg):
    print("  OK   " + msg)


def bad(msg):
    fails.append(msg)
    print("  FAIL " + msg)


def warn(msg):
    warns.append(msg)
    print("  WARN " + msg)


def code_of(version):
    """与 prepare.code_of 同一套映射（major*1e6 + minor*1e4 + patch*1e2）。

    两处必须一致，否则「自己生成、自己校验」会互相打架；这里刻意重写一份而不是
    import，是为了让 verify 能独立对着一个 zip 跑（不依赖构建机上的 prepare）。
    """
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        return -1
    return int(m.group(1)) * 1000000 + int(m.group(2)) * 10000 + int(m.group(3)) * 100


def check_files(tmp):
    print("[1] 必备文件")
    missing = [rel for rel in REQUIRED if not os.path.isfile(os.path.join(tmp, rel))]
    if missing:
        for rel in missing:
            bad("缺文件 " + rel)
    else:
        ok("%d 个必备文件齐全" % len(REQUIRED))


def check_prop(tmp, version):
    print("[2] module.prop")
    prop = {}
    with open(os.path.join(tmp, "module.prop"), encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if "=" in line:
                k, v = line.split("=", 1)
                prop[k] = v

    if prop.get("version") == version:
        ok("version = " + version)
    else:
        bad("version = %r（期望 %s）" % (prop.get("version"), version))

    want_code = str(code_of(version))
    if prop.get("versionCode") == want_code:
        ok("versionCode = " + want_code)
    else:
        bad("versionCode = %r（期望 %s）" % (prop.get("versionCode"), want_code))

    if prop.get("id") == "agent2api":
        ok("id = agent2api")
    else:
        bad("id = %r" % prop.get("id"))

    for key in ("name", "description"):
        value = prop.get(key, "")
        if not value:
            bad("%s 为空" % key)
        elif "\ufffd" in value:
            bad("%s 含替换字符（编码坏了）：%r" % (key, value))
        else:
            ok("%s 编码正常" % key)
    return prop


def check_versions(tmp, version, plugin_version):
    print("[3] 版本一致性")
    setup = open(os.path.join(tmp, "plugin-setup.sh"), encoding="utf-8").read()
    m = re.search(r"(?m)^PACK_VER=(\S+)", setup)
    pack_ver = m.group(1) if m else None
    if pack_ver == plugin_version:
        ok("plugin-setup.sh PACK_VER = " + plugin_version)
    else:
        bad("plugin-setup.sh PACK_VER = %r（期望 %s）" % (pack_ver, plugin_version))

    cust = open(os.path.join(tmp, "customize.sh"), encoding="utf-8").read()
    if "v" + plugin_version in cust:
        ok("customize.sh 提示语已同步")
    else:
        warn("customize.sh 里没有出现 v%s（安装提示可能是旧版本号）" % plugin_version)

    manifest = json.load(open(os.path.join(tmp, "plugin-pack/pack.json"), encoding="utf-8-sig"))
    if manifest.get("version") == pack_ver:
        ok("pack.json version 与 PACK_VER 一致")
    else:
        bad("pack.json version=%r != PACK_VER=%r" % (manifest.get("version"), pack_ver))

    entry = manifest.get("entry") or {}
    if "aarch64-unknown-linux-gnu" in entry:
        ok("pack.json entry 含 aarch64-unknown-linux-gnu")
    else:
        bad("pack.json entry 缺 aarch64-unknown-linux-gnu：%r" % entry)
    if len(entry) == 1:
        ok("entry 只保留 Android 那一份")
    else:
        warn("entry 里还有 %d 份地址（手机上永远匹配不到，只增体积）" % len(entry))

    if manifest.get("protocol") == 1:
        ok("protocol = 1")
    else:
        bad("protocol = %r" % manifest.get("protocol"))

    providers = manifest.get("providers") or []
    pids = {p["id"] for p in providers}
    ok("pack.json providers = %d 家" % len(providers))

    reg = json.load(open(os.path.join(tmp, "plugin-registry/plugins.json"), encoding="utf-8"))
    if len(reg.get("packs") or []) == 1:
        ok("plugins.json 单包")
    else:
        bad("plugins.json packs = %d" % len(reg.get("packs") or []))
    pack = (reg.get("packs") or [{}])[0]
    if pack.get("version") == pack_ver:
        ok("注册表 version = " + pack_ver)
    else:
        bad("注册表 version = %r" % pack.get("version"))
    if set(pack.get("providers") or {}) == pids:
        ok("注册表 providers 与 pack.json 完全一致")
    else:
        bad("注册表 providers 不一致：多 %r 少 %r" % (
            sorted(set(pack.get("providers") or {}) - pids),
            sorted(pids - set(pack.get("providers") or {}))))
    if {p["id"] for p in pack.get("manifest_providers") or []} == pids:
        ok("注册表 manifest_providers 与 pack.json 一致")
    else:
        bad("注册表 manifest_providers 不一致")
    if pack.get("entry") == "bin/agent2api-providers":
        ok("注册表 entry = bin/agent2api-providers")
    else:
        bad("注册表 entry = %r" % pack.get("entry"))

    one = json.load(open(os.path.join(tmp, "plugin-registry/registry-entry.json"), encoding="utf-8"))
    if one.get("version") == pack_ver and one.get("id") == "agent2api-providers":
        ok("registry-entry.json 同步")
    else:
        bad("registry-entry.json version=%r id=%r" % (one.get("version"), one.get("id")))
    raw = open(os.path.join(tmp, "plugin-registry/registry-entry.json"), "rb").read()
    if raw.count(b"\n") <= 1:
        ok("registry-entry.json 单行（plugin-setup 只取 head -n 1）")
    else:
        bad("registry-entry.json 有 %d 行" % raw.count(b"\n"))


def check_binaries(tmp, plugin_version):
    print("[4] 二进制")
    for rel in ("bin/agent2api-server", "plugin-pack/bin/agent2api-providers"):
        path = os.path.join(tmp, rel)
        if not os.path.isfile(path):
            continue
        blob = open(path, "rb").read()
        if blob[:4] != b"\x7fELF":
            bad(rel + " 不是 ELF")
            continue
        # e_machine 在偏移 18，小端 2 字节；0xB7 = AArch64
        if blob[18:20] != b"\xb7\x00":
            bad(rel + " 不是 aarch64（e_machine=%r）" % blob[18:20])
            continue
        found = sorted({m.group(0).decode() for m in re.finditer(rb"\d+\.\d+\.\d+", blob)})
        # 二进制里会混入各种依赖的版本号，只认「等于本版」这一条
        if plugin_version.encode() in blob:
            ok("%s 是 aarch64 ELF，内嵌 %s（%d 字节）" % (rel, plugin_version, len(blob)))
        else:
            warn("%s 里找不到 %s（可能只在网关侧；发现 %r）"
                 % (rel, plugin_version, [v for v in found if v.startswith(plugin_version[0])][:6]))


def check_frontend(tmp):
    print("[5] 前端")
    ui_dir = os.path.join(tmp, "ui")
    n = sum(len(files) for _, _, files in os.walk(ui_dir))
    if n >= 200:
        ok("ui/ %d 个文件" % n)
    else:
        bad("ui/ 只有 %d 个文件（看着像没铺全）" % n)

    for rel in ("ui/sidebar-layout.js", "ui/app.js", "ui/islands/ui.js", "ui/islands/login.js"):
        path = os.path.join(tmp, rel)
        if not os.path.isfile(path):
            continue
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        if r.returncode == 0:
            ok(rel + " 语法通过")
        else:
            bad("%s 语法错误：%s" % (rel, r.stderr.strip().splitlines()[0][:200] if r.stderr else "?"))

    app = open(os.path.join(tmp, "ui/app.js"), encoding="utf-8").read()
    for marker in ("syncUpdateBadge", "pollUpdateStatus", "updateUpdateBadge", "wbAgentPanel"):
        if marker in app:
            bad("ui/app.js 仍有 " + marker)
    ok("ui/app.js 无更新角标 / Agent 桥残留")
    if "'agent'" in app:
        bad("ui/app.js 仍有 'agent' 页面")
    else:
        ok("ui/app.js 无 agent 页面")

    sb = open(os.path.join(tmp, "ui/sidebar-layout.js"), encoding="utf-8").read()
    for marker in ("key: 'agent'", "Agent 配置"):
        if marker in sb:
            bad("ui/sidebar-layout.js 仍有 " + marker)
    ok("ui/sidebar-layout.js 无 Agent 菜单")

    uijs = open(os.path.join(tmp, "ui/islands/ui.js"), encoding="utf-8").read()
    hit = False
    for marker, label in UI_ABSENT:
        if marker in uijs:
            bad("ui.js 仍有 " + label + "（" + marker + "）")
            hit = True
    if not hit:
        ok("ui.js 已去掉全部被删功能入口")

    # install-info 是留给「详情」页的，必须还在
    if "/api/tools/install-info" in uijs:
        ok("ui.js 保留 install-info（详情页仍要显示 MCP 地址）")
    else:
        warn("ui.js 里找不到 install-info —— 详情页可能显示不出地址")


def check_routes(source):
    print("[6] 后端路由残留")
    if not source or not os.path.isdir(source):
        warn("没给 --source，跳过源码扫描")
        return
    hits = []
    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if d not in (".git", "target", "node_modules")]
        for name in files:
            if not name.endswith(".rs"):
                continue
            path = os.path.join(root, name)
            text = open(path, encoding="utf-8", errors="replace").read()
            for m in ROUTE_PAT.finditer(text):
                hits.append((os.path.relpath(path, source), m.group(1)))
    if hits:
        for rel, route in hits[:12]:
            bad("残留路由 %s: %s" % (rel, route))
    else:
        ok("没有已裁端点的路由字面量")


def check_shells(tmp):
    print("[7] shell 语法")
    bad_scripts = []
    for rel in SHELLS:
        path = os.path.join(tmp, rel)
        if not os.path.isfile(path):
            continue
        r = subprocess.run(["sh", "-n", path], capture_output=True, text=True)
        if r.returncode != 0:
            bad_scripts.append("%s：%s" % (rel, r.stderr.strip()[:160]))
    if bad_scripts:
        for item in bad_scripts:
            bad("语法错误 " + item)
    else:
        ok("%d 个脚本 sh -n 通过" % len(SHELLS))


def check_json(tmp):
    print("[8] JSON")
    targets = [
        "plugin-registry/plugins.json",
        "plugin-registry/registry-entry.json",
        "plugin-pack/pack.json",
        "plugin-pack/ui/provider-docs.json",
        "ui/manifest.webmanifest",
    ]
    for rel in targets:
        path = os.path.join(tmp, rel)
        if not os.path.isfile(path):
            warn("没有 " + rel)
            continue
        try:
            json.load(open(path, encoding="utf-8-sig"))
            ok(rel + " 合法")
        except Exception as exc:  # noqa: BLE001 - 这里就是要抓一切
            bad("%s 解析失败：%s" % (rel, exc))


def check_zip(zip_path, tmp):
    print("[9] zip 本身")
    with zipfile.ZipFile(zip_path) as z:
        broken = z.testzip()
        if broken is None:
            ok("CRC 校验通过")
        else:
            bad("CRC 损坏：" + broken)

        modes = {}
        for info in z.infolist():
            modes[info.filename] = (info.external_attr >> 16) & 0o777
        wrong = []
        for rel in EXEC:
            if rel not in modes:
                wrong.append(rel + "（缺）")
            elif modes[rel] != 0o755:
                wrong.append("%s（%o）" % (rel, modes[rel]))
        if wrong:
            for item in wrong:
                bad("权限位不对 " + item)
        else:
            ok("%d 个可执行项都是 0755" % len(EXEC))

        if all(m == 0 for m in modes.values()):
            bad("所有条目 external_attr 都是 0（安装器会丢掉权限）")
        else:
            ok("权限位已写入")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--plugin-version", required=True)
    ap.add_argument("--source", default="", help="打完补丁的上游源码目录（用于扫路由残留）")
    args = ap.parse_args()

    if not os.path.isfile(args.zip):
        sys.exit("✗ zip 不存在：" + args.zip)

    tmp = tempfile.mkdtemp(prefix="a2ab-verify-")
    try:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(tmp)
        check_files(tmp)
        check_prop(tmp, args.version)
        check_versions(tmp, args.version, args.plugin_version)
        check_binaries(tmp, args.plugin_version)
        check_frontend(tmp)
        check_routes(args.source)
        check_shells(tmp)
        check_json(tmp)
        check_zip(args.zip, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 62)
    print("失败 %d 项，警告 %d 项" % (len(fails), len(warns)))
    for item in fails:
        print("  FAIL " + item)
    for item in warns:
        print("  WARN " + item)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
