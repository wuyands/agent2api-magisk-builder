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
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "upstream.json")

GATEWAY_REPO = "aimod-cc/Agent2API"
PLUGIN_REPO = "ProvidersPlugin/Agent2Providers"


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


def _get(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent2api-magisk-builder",
        },
    )
    tok = token()
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.load(resp)


def version_key(tag, allow_prerelease=False):
    """把 `v3.4.2` / `3.4.2` / `v3.5.0-beta.7` 变成可排序的元组 `(major, minor, patch, stage)`。

    `allow_prerelease=False`（默认通道）时，带 `-beta.1` 的一律返回 None；
    为 True 时把预发布也排进来，`stage` 取该预发布的**最大数字段**：

        v3.4.2          → (3, 4, 2, 100)   正式版固定 100
        v3.5.0-beta.7   → (3, 5, 0, 7)
        v3.5.0-beta.10  → (3, 5, 0, 10)
        v3.5.0          → (3, 5, 0, 100)

    于是三条都对：`beta.10 > beta.7`（按数字比，不是字符串）、
    `3.5.0 > 3.5.0-beta.7`（同号时正式版赢）、`3.5.0-beta.1 > 3.4.2`
    （更高版本线的预发布仍大于旧正式版）。

    不能靠 API 的返回顺序 —— tags 接口的排序不是版本序（实测会给出
    v3.4.2 / v3.4.1 / v3.4.0 / v3.3.0-beta.6 … 这种近似时间序，但不能指望）。
    也不能用字符串比较：`v3.10.0` < `v3.9.0`。

    预发布段里的数字不一定是单个数字（上游发过 `v3.3.0-beta.5.1` 这种点连的），
    所以按 `.` 与 `-` 再切一层、取其中最大的数字段当 stage。
    """
    text = tag[1:] if tag.startswith("v") else tag
    if "-" in text:
        if not allow_prerelease:
            return None
        core, _, pre = text.partition("-")
        stage = 0
        for piece in re.split(r"[.\-]", pre):
            if piece.isdigit():
                stage = max(stage, int(piece))
    else:
        core, stage = text, 100

    parts = core.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return (int(parts[0]), int(parts[1]), int(parts[2]), stage)


def fetch_latest(repo, allow_prerelease=False):
    """取最新一个版本，返回 (tag, published_at)。

    两个仓库的发版习惯不一样，这里统一用 **tags** 取版本、再去 **releases**
    里捞时间：

      · 网关 aimod-cc/Agent2API —— tag 与 release 都齐全，还发过几个 beta tag；
      · 插件 ProvidersPlugin/Agent2Providers —— **release 停在 v0.2.0 没再更新**，
        真正的版本号只体现在 tag 上（v3.4.0 / v3.4.1 / v3.4.2）。如果按 releases
        查，会永远认为插件是 0.2.0，于是每天「发现有新版本」并拿一个 2026-10 的
        老 tag 去 clone，构建必然失败。

    默认跳过带 `-` 的预发布：模块是整包替换二进制的，装一个 rc 上去出问题只能靠
    人拿手机回滚，不值得为「早两天看到新功能」担这个风险。`allow_prerelease=True`
    是 beta 通道，调用方自己承担这个风险（release 会标成 prerelease）。
    """
    tags = _get("/repos/%s/tags?per_page=100" % repo)
    candidates = []
    for item in tags:
        name = (item.get("name") or "").strip()
        key = version_key(name, allow_prerelease)
        if key is not None:
            candidates.append((key, name))
    if not candidates:
        kind = "beta" if allow_prerelease else "正式"
        raise SystemExit("✗ %s 没有可用的%s tag" % (repo, kind))
    best = max(candidates)[1]

    # 时间只有 release 上有；查不到就留空（它只用于展示）
    published = ""
    try:
        for rel in _get("/repos/%s/releases?per_page=20" % repo):
            if (rel.get("tag_name") or "").strip() == best:
                published = rel.get("published_at") or ""
                break
    except Exception:  # noqa: BLE001 - 拿不到时间不影响版本判断
        pass
    return best, published


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
    ap.add_argument(
        "--channel",
        choices=("stable", "beta"),
        default="stable",
        help="stable 只看正式版（默认）；beta 连预发布一起看，取出版本号最大的那个",
    )
    args = ap.parse_args()

    beta = args.channel == "beta"

    if args.gateway:
        gw_tag, gw_at = normalize_gateway(args.gateway), ""
    else:
        gw_tag, gw_at = fetch_latest(GATEWAY_REPO, allow_prerelease=beta)
        gw_tag = normalize_gateway(gw_tag)

    if args.plugin:
        px_tag, px_at = normalize_plugin(args.plugin), ""
    else:
        px_tag, px_at = fetch_latest(PLUGIN_REPO, allow_prerelease=beta)
        px_tag = normalize_plugin(px_tag)

    state = load_state()

    # 显式给了版本号时不去查 published；但**别把已有值擦掉** ——
    # build.yml 每次构建成功都会带着 --gateway/--plugin 回写一次，
    # 如果这里写空，upstream.json 里的发布时间会被反复清掉，
    # issue 与 release notes 里就再也说不上「这是哪天上游发的版」。
    if not gw_at and state.get("gateway") == gw_tag:
        gw_at = state.get("gateway_published", "")
    if not px_at and state.get("plugin") == px_tag:
        px_at = state.get("plugin_published", "")

    # 通道也进比较：从 stable 切到 beta（或反之）而版本号恰好相同的情况是存在的
    # （例如 v3.5.0 正式发布后 beta 通道仍指向它），那时也该算「变了」，
    # 否则 daily-sync 永远不会用新通道重跑一次。
    changed = (
        (state.get("gateway") != gw_tag)
        or (state.get("plugin") != px_tag)
        or (state.get("channel", "stable") != args.channel)
    )

    print("gateway=%s" % gw_tag)
    print("plugin=%s" % px_tag)
    print("channel=%s" % args.channel)
    print("changed=%s" % ("true" if changed else "false"))

    if args.write and (changed or not args.changed_only):
        payload = {
            "gateway": gw_tag,
            "plugin": px_tag,
            "channel": args.channel,
            "gateway_published": gw_at,
            "plugin_published": px_at,
        }
        with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        sys.stderr.write(
            "已写 upstream.json：%s / %s（%s）\n" % (gw_tag, px_tag, args.channel)
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
