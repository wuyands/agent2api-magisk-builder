# -*- coding: utf-8 -*-
"""http.rs：删掉已裁功能的路由，加回精简版 install-info。

删四块：
  1. Agent 的 9 条路由（含 4 行分节注释）
  2. 工具服务「本机接入」的 6 条路由（保留 install-info）
  3. `/api/import/cc-switch`
  4. `/api/update/{*rest}`

加回 1 条：`/api/tools/install-info` —— 面板详情页要用，函数在 05 号补丁里重建过。

为什么逐条按整行文本删而不是按行号：上一轮 v3.4.1 用的是行号，v3.4.2 一来
整个 `patch_shim.py` 全废。这里每条路由都是一整行独立文本，上游插入别的东西
也不会影响命中。
"""

from base import must_replace, must_absent, must_present

TITLE = "删除已裁功能的路由（Agent / 本机接入 / cc-switch / 自更新）"

SRC = "desktop-tauri/src-tauri/server/src"
HTTP = SRC + "/server/http.rs"

AGENT_BLOCK = """        // ── Agent（本机 AI 客户端的配置接管）──
        // 全部固定路径：客户端的 id 走 body（与代理池同一约定，理由见
        // api::proxies 的模块头 —— 通配段会与 404 兜底互相干扰）。
        // 方法与形状见 api::agents 的模块头。
        .route("/api/agents", get(api::agents::list_agents))
        .route("/api/agents/profiles", post(api::agents::save_profiles))
        .route("/api/agents/apply", post(api::agents::apply_profile))
        .route("/api/agents/preview", post(api::agents::preview_profile))
        .route("/api/agents/restore", post(api::agents::restore_client))
        .route("/api/agents/import", post(api::agents::import_client))
        .route("/api/agents/{id}/resources", get(api::agent_resources::get))
        .route("/api/agents/{id}/resources/preview", post(api::agent_resources::preview))
        .route("/api/agents/{id}/resources/apply", post(api::agent_resources::apply))
"""

# 本机接入的 6 条（install-targets / install-skill / install-mcp /
# uninstall-skill / uninstall-mcp / mcp-bridge/vision.js）。
# 注意 install-info 夹在中间，所以要拆成两段删。
TOOLS_UPPER = """        .route("/api/tools/install-targets", get(api::tools::install_targets))
"""
TOOLS_LOWER = """        .route("/api/tools/install-skill", post(api::tools::install_skill))
        .route("/api/tools/install-mcp", post(api::tools::install_mcp))
        .route("/api/tools/uninstall-skill", post(api::tools::uninstall_skill))
        .route("/api/tools/uninstall-mcp", post(api::tools::uninstall_mcp))
        .route("/api/tools/mcp-bridge/vision.js", get(api::tools::vision_bridge_script))
"""

CCSWITCH_BLOCK = """        // ── 「从其他工具导入」（「导入」分段的数据源）──
        // 扫描本机 cc-switch 数据库，响应携带 API Key 明文（导入动作需要），
        // 与上面的管理接口同级敏感，挂 protected。
        .route(
            "/api/import/cc-switch",
            get(api::import_sources::scan_cc_switch),
        )
"""

UPDATE_BLOCK = """        // ── 软件更新（对照 server.mjs 749-773 行）──
        // Node 是 `path.startsWith('/api/update/')` 的前缀判定：命中后逐条比对，
        // 都不匹配则落到全局 404（不带 success 信封）。用 {*rest} 通配入口 +
        // dispatch 复刻这个结构（拆成独立路由会把「已注册路径 + 未注册方法」
        // 变成 405，与 Node 分叉）。
        // 注意：`/api/update`（没有尾斜杠）在 Node 里不命中前缀判定 → 全局 404，
        // 这里同样只注册 `{*rest}`（它要求至少一个非空段），行为一致。
        .route("/api/update/{*rest}", any(api::update::entry))
"""


def apply(root):
    p = "%s/%s" % (root, HTTP)
    removed = 0

    for block, label in [
        (AGENT_BLOCK, "Agent 9 条路由"),
        (TOOLS_UPPER, "install-targets 路由"),
        (TOOLS_LOWER, "本机接入的 5 条路由"),
        (CCSWITCH_BLOCK, "cc-switch 导入路由"),
        (UPDATE_BLOCK, "软件更新通配路由"),
    ]:
        must_replace(p, block, "", label=label)
        removed += 1

    # 工具服务分节注释里「本机接入」这个说法也要去掉
    must_replace(
        p,
        "        // 上游提供商密钥、服务开关与超时、本机接入都要管理员权限，全部挂\n",
        "        // 上游提供商密钥、服务开关与超时都要管理员权限，全部挂\n",
        label="工具服务分节注释",
    )

    # 两处提到已删模块的注释（模块头 protected 清单 + query_param 的说明）
    must_replace(
        p,
        "//!               /api/auto-checkin*、/api/update/*、\n",
        "//!               /api/auto-checkin*、\n",
        label="模块头 protected 清单里的 /api/update/*",
    )
    must_replace(
        p,
        "/// 为什么提到 HTTP 层：`/api/update` 的 `current` 与本条各有一份私有实现，\n"
        "/// 两者口径必须一致（都对应 JS 的 `URLSearchParams`），各写一份迟早会漂。\n"
        "/// 既有的那份私有实现保持原样未动（避免顺手改动已交付路径），新代码请用这个。\n",
        "/// 为什么提到 HTTP 层：网关里另有一份私有实现（`/api/update` 的 `current`，\n"
        "/// 该路由在 Android 移植里已裁），两者口径必须一致（都对应 JS 的\n"
        "/// `URLSearchParams`），各写一份迟早会漂。新代码请用这个。\n",
        label="query_param 的说明注释",
    )

    # install-info 必须还在（05 号补丁重建了函数，这里确认路由没被误删）
    must_present(
        p,
        '.route("/api/tools/install-info", get(api::tools::install_info))',
        label="install-info 路由",
    )

    # 自检：被删的路由一条都不该剩下
    for gone in [
        "/api/agents",
        "api::agent_resources::",
        "install-targets",
        "install-skill",
        "install-mcp",
        "uninstall-skill",
        "uninstall-mcp",
        "mcp-bridge/vision.js",
        "api/import/cc-switch",
        "api::import_sources::",
        "/api/update/{*rest}",
        "api::update::entry",
    ]:
        must_absent(p, gone, label="http.rs 里不应再有 %s" % gone)

    return "删除 %d 块路由，保留 install-info" % removed
