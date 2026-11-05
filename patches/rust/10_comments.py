# -*- coding: utf-8 -*-
"""清理描述「已裁功能」的注释与调试标签。

Rust 的注释不影响编译，但这些文字会误导后来的人（以及读 `/api/system-info`
截图的人）：它们描述的路由在这个移植里已经不存在了。放在最后一个补丁里做，
因为它改的都是「已经不再有代码支撑」的文字，失败也只影响可读性 ——
但按本仓的规矩，锚点没命中仍然算失败（上游改了措辞就该有人来看一眼）。

刻意**不动**的：
  · `core/cloud_sync/**` 里几十处「与 cc-switch 的 XXX 同口径」—— 那是在引用
    cc-switch 这个**别的项目**的做法当设计先例，与「从 cc-switch 导入」这个
    被裁掉的功能无关。
  · `core/update/version.rs` 与 `systemd/*` 里提到 selfupdate 的地方 —— 那里的
    自更新是真实的远端发布物解包约定，桩仍然保留同名函数定义这些约定。
  · `api/system_info.rs` 模块头提到的 `/api/update/token` —— 那是历史依据的
    出处（「只报有没有、不报值」这条纪律的来源），删掉会让纪律失去上下文。
"""

from base import must_replace, must_present

TITLE = "清理描述已裁功能的注释与调试标签"

SRC = "desktop-tauri/src-tauri/server/src"


def _p(root, rel):
    return "%s/%s/%s" % (root, SRC, rel)


def apply(root):
    edits = []

    # ── 1. server/mod.rs：模块头的路由清单 ──
    mod_rs = _p(root, "server/mod.rs")
    must_replace(
        mod_rs,
        "//!     update.rs     /api/update/*（软件更新检查 / 下载 / 进度 / 取消）\n",
        "",
        label="server/mod.rs 模块头的 update.rs 条目",
    )
    must_replace(
        mod_rs,
        "    /// 软件更新句柄（/api/update/* 四条路由）\n",
        "    /// 软件更新句柄（定时检查与插件市场的渠道跟随；对外没有更新路由）\n",
        label="server/mod.rs 的 update() 文档注释",
    )
    edits.append("server/mod.rs")

    # ── 2. server/access/diagnostics.rs：401 日志里的按路由细分 ──
    # 这段给「读更新策略被拒绝」单独写了一句影响说明。路由没了，分支也就没了。
    diag = _p(root, "server/access/diagnostics.rs")
    must_replace(
        diag,
        '        ("GET", "/api/update/policy") => "读取更新策略",\n',
        "",
        label="diagnostics.rs 的 operation 分支",
    )
    must_replace(
        diag,
        '    let impact = if method == Method::GET && path == "/api/update/policy" {\n'
        '        "本次未能读取更新策略，请求尚未进入更新处理；这条日志不表示更新服务器故障，也不代表模型提供商账号失效。"\n'
        "    } else {\n"
        '        "本次管理请求在身份验证阶段被拒绝，未执行后续操作；这条日志本身不代表模型提供商账号失效，也不代表整个网关停止工作。"\n'
        "    };\n",
        '    let impact =\n'
        '        "本次管理请求在身份验证阶段被拒绝，未执行后续操作；这条日志本身不代表模型提供商账号失效，也不代表整个网关停止工作。";\n',
        label="diagnostics.rs 的 impact 分支",
    )
    edits.append("server/access/diagnostics.rs")

    # ── 3. api/mod.rs / core/mod.rs：工具服务的模块说明 ──
    api_mod = _p(root, "server/api/mod.rs")
    must_replace(
        api_mod,
        "// 工具服务（「工具服务」页）：列表 / 开关 / 超时 / 上游提供商 / 视觉配置 /\n"
        "// 本机接入的管理面，以及对外运行时端点（Skill / MCP / REST）。上游配置与\n"
        "// 编排在 `core::tool_services`，见那两个文件模块头\n",
        "// 工具服务（「工具服务」页）：列表 / 开关 / 超时 / 上游提供商 / 视觉配置，\n"
        "// 以及对外运行时端点（Skill / MCP / REST）。上游配置与编排在\n"
        "// `core::tool_services`，见那两个文件模块头\n",
        label="api/mod.rs 的工具服务说明",
    )
    edits.append("server/api/mod.rs")

    core_mod = _p(root, "server/core/mod.rs")
    must_replace(
        core_mod,
        "// 工具服务（「工具服务」页）：网络搜索 / 视觉分析的上游配置、运行时编排与\n"
        "// 本机接入。三种对外协议（Skill / MCP / API）共享同一份上游配置，见该模块头\n",
        "// 工具服务（「工具服务」页）：网络搜索 / 视觉分析的上游配置与运行时编排。\n"
        "// 三种对外协议（Skill / MCP / API）共享同一份上游配置，见该模块头\n",
        label="core/mod.rs 的工具服务说明",
    )
    edits.append("server/core/mod.rs")

    # ── 4. core/tool_services/mod.rs：模块头 ──
    ts = _p(root, "server/core/tool_services/mod.rs")
    must_replace(
        ts,
        "//! 在「Agent 配置」（本机客户端接管）与「网络代理」之间新增的一层：对外提供\n"
        "//! 两种可选能力，客户端可以按两种可管理协议接入 ——\n"
        "//!   · Skill：打包成 Agent Skill，由面板一次性安装到本机各客户端的 skills 目录；\n"
        "//!   · MCP：Streamable HTTP 远程服务，在客户端 MCP 配置里填地址即可。\n",
        "//! 在「账号」与「网络代理」之间新增的一层：对外提供两种可选能力，客户端可以\n"
        "//! 按两种可管理协议接入 ——\n"
        "//!   · Skill：打包成 Agent Skill，客户端按 `SKILL.md` 自行装载，网关只提供\n"
        "//!     元数据与运行时接口（本机目录的安装动作随桌面端一起裁掉了）；\n"
        "//!   · MCP：Streamable HTTP 远程服务，在客户端 MCP 配置里填地址即可。\n",
        label="tool_services/mod.rs 模块头",
    )
    edits.append("server/core/tool_services/mod.rs")

    # ── 5. api/tools.rs：list_api_keys 的用途说明 ──
    tools = _p(root, "server/api/tools.rs")
    must_replace(
        tools,
        "/// GET /api/tools/api-keys —— 「本机接入」下拉用的可用网关 Key（只回 id/name/掩码）\n",
        "/// GET /api/tools/api-keys —— 面板选择「用哪个网关 Key 调工具服务」时用的清单\n"
        "/// （只回 id / name / 掩码，不回明文）\n",
        label="tools.rs 的 list_api_keys 文档",
    )
    edits.append("server/api/tools.rs")

    # ── 6. core/update/check.rs：last_check 的读者 ──
    check = _p(root, "server/core/update/check.rs")
    must_replace(
        check,
        "    /// 最近一次检查结果（`/api/update/status` 与界面首屏读它）。\n",
        "    /// 最近一次检查结果（插件市场的渠道跟随读它；Android 上没有更新路由）。\n",
        label="check.rs 的 last_check 文档",
    )
    edits.append("server/core/update/check.rs")

    # ── 7. db/backup.rs：进度实现的先例引用 ──
    backup = _p(root, "server/db/backup.rs")
    must_replace(
        backup,
        "// 与 `/api/update/progress`、`/api/storage/progress` 同一套：进度写入进程内的\n",
        "// 与 `/api/storage/progress` 同一套：进度写入进程内的\n",
        label="db/backup.rs 的进度实现说明",
    )
    edits.append("server/db/backup.rs")

    # ── 8. api/system_info.rs：模块头与 version 字段的选址说明 ──
    info = _p(root, "server/api/system_info.rs")
    must_replace(
        info,
        "//! 界面得并发打 `/api/session`、`/api/storage`、`/api/update/status`、\n"
        "//! `/api/panel/status`、`/api/config` 五条，任何一条失败就得在页面上留个\n",
        "//! 界面得并发打 `/api/session`、`/api/storage`、`/api/panel/status`、\n"
        "//! `/api/config` 四条，任何一条失败就得在页面上留个\n",
        label="system_info.rs 模块头的并发端点清单",
    )
    must_replace(
        info,
        "            // 其余形态这就是唯一真值（与 `/api/update/check` 的缺省口径一致）\n",
        "            // 其余形态这就是唯一真值。\n",
        label="system_info.rs 的 version 注释",
    )
    edits.append("server/api/system_info.rs")

    # 自检：这几个字符串一个都不该剩（都是指向已删路由的描述）
    for rel, gone in [
        ("server/mod.rs", "/api/update/*"),
        ("server/access/diagnostics.rs", "/api/update/policy"),
        ("server/api/tools.rs", "「本机接入」"),
        ("server/core/mod.rs", "本机接入"),
        ("server/api/mod.rs", "本机接入"),
        ("server/core/tool_services/mod.rs", "Agent 配置"),
        ("server/core/update/check.rs", "/api/update/status"),
        ("server/db/backup.rs", "/api/update/progress"),
    ]:
        path = _p(root, rel)
        from base import must_absent

        must_absent(path, gone, label="%s 不应再有 %s" % (rel, gone))

    # 反向自检：删注释不能把活代码删掉
    must_present(_p(root, "server/access/diagnostics.rs"), "fn operation(method: &Method, path: &str)", label="operation 还在")
    must_present(_p(root, "server/api/tools.rs"), "pub async fn list_api_keys()", label="list_api_keys 还在")
    must_present(_p(root, "server/core/update/check.rs"), "pub fn last_check(&self)", label="last_check 还在")

    return "%d 个文件的注释" % len(edits)
