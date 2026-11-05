# -*- coding: utf-8 -*-
"""clash.rs 换成恒不可用的桩。

Clash Verge 是桌面端的代理客户端，配置放在 `~/Library/Application Support/...`
或 `%APPDATA%\\...` 下。Android 上没有这个软件，也没有那些目录，原实现只会
每次启动白扫三遍磁盘再报「未找到」。

桩保留全部对外形状（`ClashSnapshot` / `ClashListener` / `CLASH_MIXED_UID` /
`CLASH_UNAVAILABLE` / `clash_snapshot()` / `clash_snapshot_with()` /
`clash_proxy_options()`），调用方一行都不用改；只把「读配置」换成「恒定不可用」。

整个文件重写而不是打补丁：原文件里的 YAML 解析、TTL 缓存、目录探测全部没有保留价值，
逐段删反而要写更多断言。
"""

from base import read, write, must_absent

TITLE = "Clash Verge 配置读取换成恒不可用桩"

SRC = "desktop-tauri/src-tauri/server/src"
CLASH = SRC + "/server/core/clash.rs"

STUB = '''//! Clash Verge 配置读取（Android 桩）。
//!
//! ── 为什么在手机上是桩 ─────────────────────────────────────
//! 原实现在本机找 Clash Verge 的配置文件（Linux / macOS `/Applications` /
//! Windows `%APPDATA%\\\\io.github.clash-verge-rev.clash-verge-rev` 三处候选），
//! 解析 `verge.yaml` 与订阅里的 `mixed-port`，供「账号代理」下拉列出可选端口。
//!
//! Android 上既没有 Clash Verge 这个桌面软件，也没有那三处目录，扫描必然全部落空 ——
//! 保留原实现只是每次冷启动白读三遍磁盘再报同一句「未找到」。
//!
//! 因此这里保留**全部对外形状**（快照结构、常量、三个入口函数），
//! 把「读配置」换成恒定返回「不可用」。调用方（`api/proxies`、`api/session`、
//! `core/egress`）一行都不用改，只是拿到的永远是 `available: false`。
//!
//! 用户仍然可以手填 HTTP / SOCKS5 代理地址 —— 那条路走配置，与本模块无关。

use serde_json::{json, Value};

/// 混合端口的伪 uid（与原实现同名同值，前端按它判定「按规则分流」）
pub const CLASH_MIXED_UID: &str = "__mixed__";

/// 「找不到配置」的固定文案（与原实现最后落到的那句一致，前端有按它做的判断）
pub const CLASH_UNAVAILABLE: &str = "未找到 Clash Verge 配置";

/// 一次 Clash Verge 配置快照。
///
/// 字段与 Node 版 `readClashVergeConfig()` 的返回一一对应
/// （available / dir / mixedPort / socksPort / httpPort / listeners /
/// currentProfileUid / error）。
#[derive(Clone, Debug, Default)]
pub struct ClashSnapshot {
    pub available: bool,
    pub dir: Option<String>,
    pub mixed_port: Option<u16>,
    pub socks_port: Option<u16>,
    pub http_port: Option<u16>,
    pub listeners: Vec<ClashListener>,
    pub current_profile_uid: Option<String>,
    pub error: Option<String>,
}

impl ClashSnapshot {
    fn unavailable(error: &str) -> Self {
        Self {
            available: false,
            dir: None,
            mixed_port: None,
            socks_port: None,
            http_port: None,
            listeners: Vec::new(),
            current_profile_uid: None,
            error: Some(error.to_string()),
        }
    }
}

/// Clash Verge 的一个混合监听器（Android 上恒为空，保留结构以维持类型形状）
#[derive(Clone, Debug)]
pub struct ClashListener {
    pub uid: String,
    pub name: String,
    pub proxy: String,
    pub port: u16,
    pub profile_uid: Option<String>,
    pub enabled: bool,
}

/// 读一次配置快照。Android 上恒为「不可用」。
pub fn clash_snapshot() -> ClashSnapshot {
    ClashSnapshot::unavailable(CLASH_UNAVAILABLE)
}

/// 强制重读的版本（原实现用来绕过 TTL 缓存）。没有缓存了，行为与 [`clash_snapshot`] 相同。
pub fn clash_snapshot_with(_force: bool) -> ClashSnapshot {
    clash_snapshot()
}

/// Clash 代理可选项（GET /api/proxies 与 /api/session 用）。
///
/// 不可用分支返回 `{available:false, error, dir, options:[]}` —— options 是空数组
/// 而不是缺失，前端 proxy-form.js 直接读 `.options.length`。
pub fn clash_proxy_options() -> Value {
    let snapshot = clash_snapshot();
    json!({
        "available": snapshot.available,
        "error": snapshot.error,
        "dir": snapshot.dir,
        "options": Vec::<Value>::new(),
    })
}
'''


def apply(root):
    p = "%s/%s" % (root, CLASH)
    write(p, STUB)
    # 自检：桩里不该再有任何读配置的痕迹
    must_absent(p, "serde_yaml", label="clash.rs 不应再依赖 serde_yaml")
    must_absent(p, "read_clash_verge_config", label="clash.rs 不应再有原函数")
    return "换成 %d 行桩" % STUB.count("\n")
