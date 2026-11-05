# -*- coding: utf-8 -*-
"""tools.rs：删掉「本机接入」，只保留一个纯元数据版的 install-info。

「本机接入」做的是「把 Skill / MCP 配置写进本机客户端的目录」（~/.claude、
~/.codex…）。手机上没有这些客户端，写入目标不存在，整块去掉。

但 `/api/tools/install-info` 这一个接口要留着 —— 面板的「工具服务详情」页
靠它显示服务名、版本、超时、MCP 地址、Skill 变体（前端 `EWe` 组件的
`g.useEffect` 里调 `sWe`）。它只**读元数据**，不写任何文件。
这里保留它，去掉其中的 `bridge_url` —— 那是「视觉本地桥接脚本」的下载地址，
桥接脚本本身已经删了，留着就是一个指向 404 的链接。

`plain_key` / `client_ids` / `outcomes_json` 三个辅助函数只服务于
install / uninstall，一并删掉。

删法说明：`本机接入` 这一整段正好是文件尾部（从分节注释到文件末尾的
`vision_bridge_script`），所以按「找到分节标记 → 截断到那里 → 追加精简版
install_info」处理，比按行号可靠。
"""

from base import read, write, must_replace, must_absent, must_present, PatchError

TITLE = "工具服务：删掉「本机接入」，保留纯元数据版 install-info"

SRC = "desktop-tauri/src-tauri/server/src"
TOOLS = SRC + "/server/api/tools.rs"

ANCHOR = "/* ─── 本机接入"

INSTALL_INFO = '''/// GET /api/tools/install-info?service=web-search
///
/// 只回元数据：服务名、版本、超时、MCP 地址、Skill 变体清单。
/// 面板的「详情」页据此拼出「怎么连」，自己不写任何本机文件。
pub async fn install_info(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Response {
    let service = query.get("service").map(String::as_str).unwrap_or("");
    if !tool_services::is_service(service) {
        return errors::management_error(400, "未知的工具服务");
    }
    let base = base_url(&headers, &state);
    let tools: Vec<&str> = if service == tool_services::WEB_SEARCH_SERVICE_ID {
        vec!["web_search", "web_fetch"]
    } else {
        vec!["image_analyze"]
    };
    let mut value = json!({
        "base_url": base,
        "service": service,
        "name": tool_services::package_name(service),
        "version": tool_services::version(service),
        "timeout_seconds": tool_services::timeout_seconds(service),
        "mcp": {
            "server_name": tool_services::package_name(service),
            "url": format!("{}{}", base.trim_end_matches('/'), tool_services::endpoint(service, "mcp")),
            "tools": tools,
        },
    });
    if service == tool_services::WEB_SEARCH_SERVICE_ID {
        value["skill"] = json!({
            "name": tool_services::WEB_SEARCH_SKILL_NAME,
            "version": tool_services::WEB_SEARCH_SKILL_VERSION,
            "recommended_variant": tool_services::recommended_skill_variant(),
            "variants": tool_services::skill_variants(),
        });
    }
    ok_json(value)
}
'''


def apply(root):
    p = "%s/%s" % (root, TOOLS)
    text = read(p)

    # ── 1. 模块头：这两行描述的功能已经不存在 ──
    must_replace(
        p,
        "//! - 本机接入：安装 / 卸载 Skill 与 MCP 配置，安装目标探测；\n"
        "//! - 视觉本地桥接脚本的下载（面板安装时直接取用）。\n",
        "",
        label="tools.rs 模块头",
    )

    # ── 2. 从「本机接入」分节标记截断到文件末尾 ──
    text = read(p)
    hits = text.count(ANCHOR)
    if hits != 1:
        raise PatchError(
            "%s\n  「本机接入」分节标记期望 1 次，实际 %d 次" % (TOOLS, hits)
        )
    cut = text.index(ANCHOR)
    kept = text[:cut].rstrip("\n") + "\n"

    # 确认截断点之前的最后一个函数是 test_vision，别把别的代码一起带走
    if "pub async fn test_vision" not in kept:
        raise PatchError("%s\n  截断后找不到 test_vision —— 分节标记位置不对" % TOOLS)
    write(p, kept)

    # ── 3. 追加精简版 install_info ──
    write(p, read(p) + "\n" + INSTALL_INFO)

    # ── 4. 清掉不再使用的 axum 导入（IntoResponse 只被已删的 vision_bridge_script 用）──
    must_replace(
        p,
        "use axum::response::{IntoResponse, Response};",
        "use axum::response::Response;",
        label="tools.rs 的 axum 导入",
    )

    # ── 5. 自检 ──
    for gone in [
        "pub async fn install_targets",
        "pub async fn install_skill",
        "pub async fn install_mcp",
        "pub async fn uninstall_skill",
        "pub async fn uninstall_mcp",
        "pub async fn vision_bridge_script",
        "fn plain_key",
        "fn client_ids",
        "fn outcomes_json",
        "bridge_url",
        "VISION_BRIDGE_SCRIPT",
        "InstallOutcome",
    ]:
        must_absent(p, gone, label="tools.rs 里不应再有 %s" % gone)
    must_present(p, "pub async fn install_info", label="install_info 必须保留")
    must_present(p, "pub async fn list_api_keys", label="list_api_keys 必须保留")
    must_present(p, "pub async fn test_vision", label="test_vision 必须保留")

    return "本机接入已删，install-info 精简为纯元数据"
