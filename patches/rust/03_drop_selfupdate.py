# -*- coding: utf-8 -*-
"""摘掉「容器内自更新」的执行能力，保留更新检查。

`core/update` 这个目录不能整块删 —— 插件市场（`plugin_host/settings.rs`）和
模型元数据（`core/model_meta`）都在复用它的检查间隔设置与出网探测。
真正该去掉的只是三样：
  · `selfupdate.rs` 整个文件（换二进制、解包、重启钩子）—— 已在上一步删掉
  · `UpdateManager.pending_restart` 字段与 `install_downloaded` / `request_restart`
  · check 响应里的 `selfUpdate` / `pendingRestart` 两个字段

Android 上模块由 Magisk 管理，二进制在只读的模块目录里，进程也没有权限替换自己；
「面板点一下就原地更新」这条路根本走不通，留着的唯一效果是给出一个必然失败的按钮。
"""

from base import must_cut_range, must_replace, must_absent

TITLE = "摘掉容器内自更新（保留更新检查）"

SRC = "desktop-tauri/src-tauri/server/src"
MOD = SRC + "/server/core/update/mod.rs"


def apply(root):
    p = "%s/%s" % (root, MOD)

    # ── 1. Inner 里的 pending_restart 字段 ──
    must_replace(
        p,
        "    /// 容器内更新已应用、但进程还没重启（只活在内存里，重启即自然清零）。\n"
        "    ///\n"
        "    /// 挡「同一版重复安装」：新版本已就位、只差重启时不再重复替换文件。\n"
        "    pending_restart: bool,\n",
        "",
        label="Inner.pending_restart 字段",
    )
    must_replace(
        p,
        "                download_dir: directory.join(\"updates\"),\n"
        "                pending_restart: false,\n",
        "                download_dir: directory.join(\"updates\"),\n",
        label="UpdateManager::new 里的初始化",
    )

    # ── 2. build_check_result 里的取用与输出 ──
    must_replace(
        p,
        "        let (latest, repository, download_dir, task, pending_restart) = {\n"
        "            let guard = self.lock();\n"
        "            (\n"
        "                guard.latest.clone(),\n"
        "                guard.repository.clone(),\n"
        "                guard.download_dir.clone(),\n"
        "                guard.task.clone(),\n"
        "                guard.pending_restart,\n"
        "            )\n"
        "        };\n",
        "        let (latest, repository, download_dir, task) = {\n"
        "            let guard = self.lock();\n"
        "            (\n"
        "                guard.latest.clone(),\n"
        "                guard.repository.clone(),\n"
        "                guard.download_dir.clone(),\n"
        "                guard.task.clone(),\n"
        "            )\n"
        "        };\n",
        label="build_check_result 的解构",
    )
    must_replace(
        p,
        "            // ── 容器内更新（Linux / Docker）──────────────────────\n"
        "            // selfUpdate 说的是「这个部署能不能原地更新」（平台 + 环境开关），\n"
        "            // serverAsset 说的是「这一版有没有可下的包」—— 两者分开，面板才能\n"
        "            // 区分「本部署不支持」与「该版本没提供更新包」这两种不同的提示。\n"
        '            "selfUpdate": selfupdate::supported(),\n',
        "            // Android 模块由 Magisk 管理二进制，进程无权替换自己 —— 恒为 false，\n"
        "            // 面板据此不显示「容器内更新」相关入口。\n"
        '            "selfUpdate": false,\n',
        label="check 响应的 selfUpdate",
    )
    must_replace(
        p,
        "            // 已应用、只差重启：界面据此把按钮换成「立即重启」，\n"
        "            // 而不是再给一次注定 400 的「下载并更新」\n"
        '            "pendingRestart": pending_restart,\n',
        "",
        label="check 响应的 pendingRestart",
    )

    # ── 3. 整段删掉 install_downloaded + request_restart ──
    # 从「容器内更新」的分节注释开始，到 request_restart 的收尾大括号为止。
    must_cut_range(
        p,
        "    // ─── 容器内更新（Docker / Linux headless）",
        # 结束标记必须落在**单行**上：must_cut_range 逐行做子串匹配，
        # 多行标记永远匹配不上（第一版就栽在这）。
        '        Ok(json!({ "restarting": true }))',
        label="install_downloaded 与 request_restart",
        # 结束标记落在 request_restart 的最后一条语句上，紧跟的收尾大括号
        # （`    }`）不在标记里 —— 漏删会留下一个多余的右大括号，编译器报
        # `unexpected closing delimiter`。那一行没有独特文本可当锚点，只能按
        # 「相对结束标记的偏移」连带删掉。
        tail=1,
    )

    must_absent(p, "selfupdate::", label="update/mod.rs 里不应再有 selfupdate 引用")

    # 删掉 install_downloaded / request_restart 之后，`Path` 在本文里就没人用了
    # （只剩 `download_dir: PathBuf` 那几处）。上游写的是 `{Path, PathBuf}`，
    # 留着会报 `unused import: Path` —— 我们的改动自己弄出来的告警，自己清掉。
    must_replace(
        p,
        "use std::path::{Path, PathBuf};",
        "use std::path::PathBuf;",
        label="update/mod.rs 的 Path 导入",
    )

    return "摘掉自更新执行路径"
