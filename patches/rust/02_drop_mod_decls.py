# -*- coding: utf-8 -*-
"""删掉上一步移除的文件留下的模块声明。

删完文件后 `pub mod agents;` 这类声明会指向不存在的文件，编译直接报 E0583。
这里把声明连同它上方的说明注释一起删掉 —— 注释留着会描述一个不存在的模块。

── 为什么不是「两行一起删」 ──────────────────────────────────
v3.4.2 里 `pub mod agents;` 与 `pub mod agent_resources;` 是紧挨着的，一条替换
就能带走两行。v3.5 在上游插进了 `pub mod advertisements;`，两行被拆开了 ——
按「相邻」写的锚点必然失效。改成一行一行删，中间夹了什么新模块都不影响。
`mod bridge;` / `mod install;` 同理（v3.5 在两者之间插了 `image_bridge` 三行）。
"""

from base import must_replace

TITLE = "清理模块声明"

SRC = "desktop-tauri/src-tauri/server/src"

# (文件, 原文, 替换成)
EDITS = [
    # ── api/mod.rs ──
    (
        SRC + "/server/api/mod.rs",
        "// 「Agent」页：本机 AI 客户端配置接管（列表 / 保存 / 写入 / 预览 / 还原 / 导入）\n"
        "pub mod agents;\n",
        "",
    ),
    (
        SRC + "/server/api/mod.rs",
        "pub mod agent_resources;\n",
        "",
    ),
    (
        SRC + "/server/api/mod.rs",
        "// 「从其他工具导入」的扫描接口（当前来源：cc-switch；存储读取见\n"
        "// `core::import_ccswitch`）\n"
        "pub mod import_sources;\n",
        "",
    ),
    (
        SRC + "/server/api/mod.rs",
        "pub mod update;\n",
        "",
    ),
    # 模块头注释里那一行 /api/update/*
    (
        SRC + "/server/api/mod.rs",
        "//!   update.rs     /api/update/*（软件更新检查 / 下载 / 进度 / 取消）\n",
        "",
    ),
    # ── core/mod.rs ──
    (
        SRC + "/server/core/mod.rs",
        "// 本机 AI 客户端的接管注册表（「Agent」页）：客户端定义 + 配置读写\n"
        "pub mod agents;\n",
        "",
    ),
    (
        SRC + "/server/core/mod.rs",
        "pub mod import_ccswitch;\n",
        "",
    ),
    # ── tool_services/mod.rs ──
    (
        SRC + "/server/core/tool_services/mod.rs",
        "mod bridge;\n",
        "",
    ),
    (
        SRC + "/server/core/tool_services/mod.rs",
        "mod install;\n",
        "",
    ),
    (
        SRC + "/server/core/tool_services/mod.rs",
        "pub use bridge::VISION_BRIDGE_SCRIPT;\n",
        "",
    ),
    (
        SRC + "/server/core/tool_services/mod.rs",
        "pub use install::{\n"
        "    install_mcp, install_skill, mcp_targets, skill_targets, uninstall_mcp, uninstall_skill,\n"
        "    InstallOutcome,\n"
        "};\n",
        "",
    ),
    # ── update/mod.rs：`pub mod selfupdate;` **保留** ──
    # 该模块的文件没删，只是被补丁 08 换成了「永远不支持」的桩；声明必须还在，
    # 否则 `systemd/mod.rs`、`capabilities.rs` 里的调用点解析不到。
    # 只改它上面那段描述「headless 入口注册重启钩子」的注释 —— 重启钩子已经
    # 不存在了，注释留着会误导后来的人。
    (
        SRC + "/server/core/update/mod.rs",
        "// 容器内自更新：headless 入口注册重启钩子（`set_restart_hook`）要用它，\n"
        "// 所以对本 crate 之外也要可见（桌面形态不注册，该模块的函数在非 Linux 上\n"
        "// 一律返回「不支持」）。\n"
        "pub mod selfupdate;\n",
        "// 容器内自更新 —— 在 Android 移植里是「永远不支持」的桩（见该模块头）。\n"
        "// 声明保留是因为 `systemd` 与 `capabilities` 里有几处不带 `#[cfg]` 门控的\n"
        "// 调用点要能解析；真正的更新由 Magisk 整包替换模块目录。\n"
        "pub mod selfupdate;\n",
    ),
]


def apply(root):
    for rel, old, new in EDITS:
        must_replace("%s/%s" % (root, rel), old, new, label="%s 的模块声明" % rel)
    return "%d 处声明" % len(EDITS)
