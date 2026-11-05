#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问上游「现在最新是哪一版」，并与仓库里记着的 upstream.json 比对。

两个仓库分别出问题，所以要分开看：

  · 网关 aimod-cc/Agent2API —— 决定模块版本、决定要打哪份补丁
  · 插件 ProvidersPlugin/Agent2Providers —— 决定插件包版本与 34 家实现

两者的版本**不一定同步**：网关 v3.4.2 的 Cargo.toml 至今仍钉 `tag = "v3.4.0"`
引用插件仓库的协议库，而插件仓库自己已经走到 v3.4.2。协议号（protocol=1）
相同就能混跑，所以这里不做「必须同版本」的假设，各取各的。

输出（给 CI 直接吃）：
    gateway=v3.4.2
    plugin=3.4.2
    changed=true

用 `--write` 时把结果写回 upstream.json（`--changed-only` 时只有真的变了才写）。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "upstream.json")

GATEWAY_REPO = "aimod-cc/Agent2API"
PLUGIN_REPO = "ProvidersPlugin/Agent2Providers"

API = "https://api.github.com/repos/%s/releases"


def token():
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    # 本地跑：gh 已经登录过就直接借它的 token
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=20
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:  # noqa: BLE001 - 本地没装 gh 是正常情况
        pass
    return ""


def fetch_latest(repo):
    """取最新一个**正式** release 的 tag，返回 (tag, published_at)。

    跳过 prerelease / draft：模块是整包替换二进制的，装一个 rc 上去出问题
    只能靠人拿手机回滚，不值得为「早两天看到新功能」担这个风险。
    """
    req = urllib.request.Request(API % repo, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "agent2api-magisk-builder",
    })
    tok = token()
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=45) as resp:
        releases = json.load(resp)

    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = (rel.get("tag_name") or "").strip()
        if tag:
            return tag, rel.get("published_at") or ""
    raise SystemExit("✗ %s 没有正式 release" % repo)


def normalize_gateway(tag):
    return tag if tag.startswith("v") else "v" + tag


def normalize_plugin(tag):
    return tag[1:] if tag.startswith("v") else tag


def load_state():
    if not os.path.isfile(STATE):
        return {}
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 - 状态文件坏了就当没有
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="把结果写回 upstream.json")
    ap.add_argument("--changed-only", action="store_true", help="只有版本变了才写")
    ap.add_argument("--gateway", default="", help="强制指定网关版本（跳过查询）")
    ap.add_argument("--plugin", default="", help="强制指定插件版本（跳过查询）")
    args = ap.parse_args()

    if args.gateway:
        gw_tag, gw_at = normalize_gateway(args.gateway), ""
    else:
        gw_tag, gw_at = fetch_latest(GATEWAY_REPO)
        gw_tag = normalize_gateway(gw_tag)

    if args.plugin:
        px_tag, px_at = normalize_plugin(args.plugin), ""
    else:
        px_tag, px_at = fetch_latest(PLUGIN_REPO)
        px_tag = normalize_plugin(px_tag)

    state = load_state()
    changed = (state.get("gateway") != gw_tag) or (state.get("plugin") != px_tag)

    print("gateway=%s" % gw_tag)
    print("plugin=%s" % px_tag)
    print("changed=%s" % ("true" if changed else "false"))

    if args.write and (changed or not args.changed_only):
        payload = {
            "gateway": gw_tag,
            "plugin": px_tag,
            "gateway_published": gw_at,
            "plugin_published": px_at,
        }
        with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        sys.stderr.write("已写 upstream.json：%s / %s\n" % (gw_tag, px_tag))

    return 0


if __name__ == "__main__":
    sys.exit(main())
