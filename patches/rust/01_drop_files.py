# -*- coding: utf-8 -*-
"""裁掉「本机客户端接管」相关的整块文件和整目录。

对应功能：Agent 配置页（读写本机桌面客户端配置文件）+ 工具服务的「本机接入」
（把 Skill / MCP 安装到本机客户端目录）+ cc-switch 导入。

为什么在 Android 上没有意义：这三件事的对象都是「桌面客户端在本机的配置文件目录」
（~/.claude、~/.codex、~/Library/Application Support/...）。手机上既没有这些客户端，
也没有那些路径。留着只会让面板出现一堆点了报错的按钮。

删文件比改代码安全：删掉之后编译器会直接把所有引用点报出来，改代码则可能留下
「能编过但语义已死」的残留。
"""

from base import must_delete_file, must_delete_tree

TITLE = "删除 Agent 接管 / 本机接入 / cc-switch 导入的全部实现文件"

SRC = "desktop-tauri/src-tauri/server/src"

FILES = [
    # ── Agent 配置页 ──
    SRC + "/server/api/agents.rs",
    SRC + "/server/api/agent_resources.rs",
    # ── cc-switch 导入 ──
    SRC + "/server/api/import_sources.rs",
    SRC + "/server/core/import_ccswitch.rs",
    # ── 软件更新 API（自更新在安卓上没有意义，check/download 仍被插件市场复用，
    #    但那些在 core/update 里，api/update 只是面板入口）──
    #
    # 注意：`server/core/update/selfupdate.rs` **不在这里删**。
    # 它有 77 处引用，其中 `systemd/mod.rs` 与 `capabilities.rs` 里的几处不带
    # `#[cfg]` 门控，Android 上照样参与编译；`systemd/files.rs` 还拿它的
    # `extract_bundle()` 解 tar.gz。删文件就得把 200 行解包逻辑搬到别处，
    # 收益为零。改由补丁 08 把实现换成「永远不支持」的桩，签名不动。
    SRC + "/server/api/update.rs",
    # ── 工具服务的「本机接入」──
    SRC + "/server/core/tool_services/install.rs",
    SRC + "/server/core/tool_services/bridge.rs",
]

TREES = [
    # Agent 接管的核心逻辑（30+ 文件，6000+ 行）
    SRC + "/server/core/agents",
]


def apply(root):
    removed = 0
    for rel in FILES:
        must_delete_file("%s/%s" % (root, rel))
        removed += 1
    for rel in TREES:
        must_delete_tree("%s/%s" % (root, rel))
        removed += 1
    return "删除 %d 个文件 + %d 个目录" % (len(FILES), len(TREES))
