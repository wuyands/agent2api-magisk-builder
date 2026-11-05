# -*- coding: utf-8 -*-
"""把「容器内自更新」换成不支持桩，而不是删文件。

## 为什么不能删文件

`server/core/update/selfupdate.rs`（601 行）在上游负责「面板点一下就在原地
替换二进制并重启进程」，只对 Docker / Linux headless 有意义。按最初的思路
直接 `rm` 掉，结果补丁 08 在真跑时报「仍然引用 selfupdate」—— 全仓有 77 处
引用，其中两处**没有 `#[cfg]` 门控，Android 上照样参与编译**：

  · `server/core/update/systemd/mod.rs:31`
    `if super::selfupdate::current_exe_path().ok()...`（在 `unavailable_reason()` 里）
  · `server/core/update/capabilities.rs:5` / `:23`
    `use super::{selfupdate, systemd, version};` + `"docker" if selfupdate::supported()`

还有 `systemd/files.rs:58` 拿 `selfupdate::extract_bundle()` 解 tar.gz ——
那是 200 行手写 tar 解析，删模块就得把它搬到别处，收益为零。

## 桩的契约

保留**同一套公开签名**，行为换成「永远不支持」：

  enabled()        → false      （`AGENT2API_SELF_UPDATE` 开关不再有意义）
  supported()      → false      （面板据此不显示「下载并更新」入口）
  bundle_name()    → None
  request_restart()→ false      （没有钩子 = 调用方拒绝请求）
  set_restart_hook → 空操作     （headless 入口不再注册）
  extract_bundle() → Err
  apply()          → Err
  current_exe_path / file_sha256 保留真实现（纯粹的路径与哈希计算，
  被 systemd 与 windows_service 的判定逻辑引用，改掉反而引入无谓差异）

再把 `.sha256` 校验那条也换成 Err —— 它要出网。

上游 `core/update/mod.rs` 里真正会走到替换文件的 `install_downloaded` /
`request_restart` 已由补丁 03 整段删除，所以运行期没有任何路径能落到桩上：
桩只保证「编译期形状不变、运行期必然拒绝」。

真正负责更新的是 Magisk（`magisk --install-module` 整包替换模块目录）。
"""

from base import write, must_absent, must_present

TITLE = "容器内自更新换成不支持桩（保留签名，删实现）"

SRC = "desktop-tauri/src-tauri/server/src"
PATH = SRC + "/server/core/update/selfupdate.rs"

BODY = r'''//! 容器内自更新 —— **不支持桩**（Android 移植）。
//!
//! 上游这个模块负责「面板点一下就在原地替换二进制、再重启进程」，那是给
//! Docker / Linux headless 部署用的：
//!
//!   · 解 `.tar.gz` 更新包（手写 tar 解析 + 路径穿越防护）
//!   · 校验 `.sha256` 伴随文件
//!   · 同目录原子替换二进制、复制-删除-改名替换 `ui/`
//!   · 注册重启钩子，让新进程替上来
//!
//! Android 上这条路走不通：二进制躺在 Magisk 模块目录里，由
//! `magisk --install-module` 整包替换；模块目录是只读的，网关进程也没有
//! 权限替换自己。留着的唯一效果是给面板一个必然失败的按钮。
//!
//! 但**文件不能删**：`core/update/systemd/mod.rs` 与 `capabilities.rs` 里有
//! 几处不带 `#[cfg]` 门控的调用（`current_exe_path()` / `supported()`），
//! Android 上照样参与编译。所以保留同一套签名、行为换成「永远不支持」——
//! 编译期形状不变，运行期没有任何路径能落到真正替换文件的地方。
//!
//! 上游会走到替换流程的 `install_downloaded` / `request_restart` 已被
//! 移植补丁整段删除，这里只是给剩下的引用点留一个能解析、且永远说「不」的
//! 实现。真正的更新由 Magisk 负责。

use std::io::Read;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

use super::version::UpdateError;

/// 部署开关：上游读 `AGENT2API_SELF_UPDATE`。Android 上恒关。
#[allow(dead_code)]
pub fn enabled() -> bool {
    false
}

/// 本部署是否可用容器内更新。Android 恒 `false`。
#[allow(dead_code)]
pub fn supported() -> bool {
    false
}

/// 本机架构对应的更新包名。Android 不走容器内更新，恒 `None`。
#[allow(dead_code)]
pub fn bundle_name() -> Option<String> {
    None
}

/// 当前可执行文件的真实路径（解析符号链接）。
///
/// 保留真实现：`systemd::unavailable_reason()` 拿它判断「自己是不是装在
/// /opt/agent2api」，那是个纯粹的路径比较，与更新能力无关。
pub fn current_exe_path() -> Result<PathBuf, UpdateError> {
    let exe = std::env::current_exe()
        .map_err(|error| UpdateError::new(format!("无法定位当前可执行文件：{error}")))?;
    Ok(std::fs::canonicalize(&exe).unwrap_or(exe))
}

/// 取 `.sha256` 伴随文件里的期望哈希。要出网，Android 上直接拒绝。
#[allow(dead_code)]
pub async fn fetch_checksum(_url: &str) -> Result<String, UpdateError> {
    Err(UpdateError::new("Android 模块不支持容器内更新"))
}

/// 文件内容的 sha256（十六进制小写，流式读取，不整包进内存）。
///
/// 保留真实现：`systemd/worker.rs` 与 `windows_service/worker.rs` 拿它做
/// 升级程序副本校验，都是纯计算。
pub fn file_sha256(path: &Path) -> Result<String, UpdateError> {
    let mut file = std::fs::File::open(path)
        .map_err(|error| UpdateError::new(format!("打开文件失败：{error}")))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| UpdateError::new(format!("读取文件失败：{error}")))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

/// 解包结果（二进制是否拿到、界面文件写了几个）。
///
/// 形状与上游一致，供 `systemd/files.rs` 的返回类型解析。
#[allow(dead_code)]
pub struct Extracted {
    pub binary: bool,
    pub ui_files: usize,
}

/// 把归档解到两个暂存目录。Android 上恒失败。
#[allow(dead_code)]
pub fn extract_bundle(
    _archive: &Path,
    _bin_stage: &Path,
    _ui_stage: Option<&Path>,
) -> Result<Extracted, UpdateError> {
    Err(UpdateError::new("Android 模块不支持容器内更新"))
}

/// 安装结果（界面目录有没有一起换掉）。
#[allow(dead_code)]
pub struct ApplyOutcome {
    pub ui_updated: bool,
}

/// 应用更新包。Android 上恒失败。
#[allow(dead_code)]
pub fn apply(
    _archive: &Path,
    _exe: &Path,
    _ui_dir: Option<&Path>,
) -> Result<ApplyOutcome, UpdateError> {
    Err(UpdateError::new(
        "Android 模块由 Magisk 整包替换，不支持原地更新",
    ))
}

// ─── 重启 ───────────────────────────────────────────────────

/// 注册重启钩子。Android 上没有「面板发起的重启」这条路，空操作。
#[allow(dead_code)]
pub fn set_restart_hook(_hook: Box<dyn Fn() + Send + Sync>) {}

/// 请求重启。恒 `false` —— 调用方据此拒绝请求，而不是静默什么都不做。
#[allow(dead_code)]
pub fn request_restart() -> bool {
    false
}
'''


def apply(root):
    p = "%s/%s" % (root, PATH)

    # 桩覆盖整个文件（上游 601 行 → 约 150 行）。
    # 覆盖而不是逐段删：解包逻辑分散在十几个私有函数里，逐段删更容易出错。
    write(p, BODY)

    # 断言：签名齐全（下游 systemd / capabilities / windows_service 都要解析到）
    for symbol in (
        "pub fn enabled()",
        "pub fn supported()",
        "pub fn bundle_name()",
        "pub fn current_exe_path()",
        "pub async fn fetch_checksum(",
        "pub fn file_sha256(",
        "pub struct Extracted",
        "pub fn extract_bundle(",
        "pub struct ApplyOutcome",
        "pub fn apply(",
        "pub fn set_restart_hook(",
        "pub fn request_restart()",
    ):
        must_present(p, symbol, label="桩缺少 %s" % symbol)

    # 断言：真正的替换/解包实现已经没了
    for gone in (
        "flate2",
        "replace_file",
        "replace_dir",
        "rename(",
        "std::process::Command",
        "RESTART_HOOK",
        "USER_AGENT",
    ):
        must_absent(p, gone, label="桩里不应再有 %s" % gone)

    # 断言：能力判定恒假
    must_present(p, "pub fn supported() -> bool {\n    false\n}", label="supported 恒假")
    must_present(p, "pub fn enabled() -> bool {\n    false\n}", label="enabled 恒假")

    return "selfupdate.rs 换成不支持桩（601 行 → 桩，12 个签名保留）"
