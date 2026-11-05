# -*- coding: utf-8 -*-
"""bin/agent2api-server.rs：摘掉「面板发起的重启」通道。

原实现让面板点「安装并重启」时往主线程发信号，走 SIGTERM 那条路优雅停机，
再由外部监管者（容器 restart 策略 / systemd / SCM）把新进程拉起来。

Android 上这道机制两头都空：没有任何监管者会拉起进程（是 `service.sh` 在开机时
启动的一次性进程），二进制在只读模块目录里也换不掉。留着的话只会多一条永远
发不出信号的 channel、一段永远不触发的 select 分支，以及一个读不到的配置项。
"""

from base import must_replace, must_cut_range, must_absent

TITLE = "摘掉面板重启通道"

SRC = "desktop-tauri/src-tauri/server/src"
BIN = SRC + "/bin/agent2api-server.rs"


def apply(root):
    p = "%s/%s" % (root, BIN)

    # ── 1. Running 结构只剩 shutdown_tx ──
    must_replace(
        p,
        "struct Running {\n"
        "    shutdown_tx: tokio::sync::oneshot::Sender<()>,\n"
        "    /// 面板「安装并重启」的信号（容器内更新用）\n"
        "    restart_rx: tokio::sync::mpsc::Receiver<()>,\n"
        "}\n",
        "struct Running {\n"
        "    shutdown_tx: tokio::sync::oneshot::Sender<()>,\n"
        "}\n",
        label="Running 结构",
    )

    # ── 2. 主流程解构 + 等待信号 ──
    must_replace(
        p,
        "    let Running {\n"
        "        shutdown_tx,\n"
        "        restart_rx,\n"
        "    } = running;\n"
        "    runtime.block_on(wait_for_shutdown_signal(restart_rx));\n",
        "    let Running { shutdown_tx } = running;\n"
        "    runtime.block_on(wait_for_shutdown_signal());\n",
        label="主流程解构",
    )

    # ── 3. 重启钩子注册块（5 行注释 + 6 行代码 + 空行）──
    must_replace(
        p,
        "    // 「面板发起的重启」通道：面板点了「安装并重启」之后，自更新模块的钩子\n"
        "    // 往这里发一个信号，主线程照 SIGTERM 那条路优雅停机并返回 —— 服务由\n"
        "    // 外部监管者拉起（容器 restart 策略 / systemd Restart= / SCM 恢复策略）。\n"
        "    //\n"
        "    // 放 start() 之前注册：请求只会由正在跑的服务器发来，而钩子只需要这个\n"
        "    // 发送端（停机动作仍在主线程做，见 `finish`）。\n"
        "    let (restart_tx, restart_rx) = tokio::sync::mpsc::channel::<()>(1);\n"
        "    agent2api_server::server::core::update::selfupdate::set_restart_hook(Box::new(move || {\n"
        "        // 钩子跑在自更新的后台线程里：try_send 不阻塞、也不要求运行时上下文\n"
        "        let _ = restart_tx.try_send(());\n"
        "    }));\n"
        "\n",
        "",
        label="重启钩子注册",
    )

    # ── 4. start_gateway 的返回值 ──
    must_replace(
        p,
        "    Ok(Running {\n"
        "        shutdown_tx,\n"
        "        restart_rx,\n"
        "    })\n",
        "    Ok(Running { shutdown_tx })\n",
        label="start_gateway 返回值",
    )

    # ── 5. Windows 服务形态的 select ──
    must_replace(
        p,
        "        let Running {\n"
        "            shutdown_tx,\n"
        "            mut restart_rx,\n"
        "        } = start_gateway(&launch)?;\n",
        "        let Running { shutdown_tx } = start_gateway(&launch)?;\n",
        label="SCM 形态的解构",
    )
    must_replace(
        p,
        "        // 停机有两条来源，收尾路径相同：\n"
        "        //   · SCM 的 STOP / SHUTDOWN 控制事件（`sc.exe stop`、关机）；\n"
        "        //   · 面板「安装并重启」的自更新钩子（替文件后要求进程退出，\n"
        "        //     由 SCM 的恢复策略把新版本拉起来 —— 与容器 restart 同语义）。\n",
        "        // 停机只有一条来源：SCM 的 STOP / SHUTDOWN 控制事件\n"
        "        // （`sc.exe stop`、关机）。\n",
        label="SCM 形态的停机说明",
    )
    must_replace(
        p,
        "            tokio::select! {\n"
        "                _ = stop.into_async().wait() => {}\n"
        "                _ = restart_rx.recv() => {}\n"
        "            }\n",
        "            stop.into_async().wait().await;\n",
        label="SCM 形态的 select",
    )

    # ── 6. 停机信号函数去掉 restart 参数与两个分支 ──
    must_replace(
        p,
        "/// 等待停机信号：Ctrl+C（全平台）、SIGTERM（unix，容器 stop 走这条），\n"
        "/// 或面板发起的重启（外部监管者拉起新进程，见 `start_gateway` 的说明）。\n"
        "async fn wait_for_shutdown_signal(mut restart: tokio::sync::mpsc::Receiver<()>) {\n",
        "/// 等待停机信号：Ctrl+C（全平台）、SIGTERM（unix，`kill` 走这条）。\n"
        "async fn wait_for_shutdown_signal() {\n",
        label="wait_for_shutdown_signal 签名",
    )
    must_replace(
        p,
        "        tokio::select! {\n"
        "            _ = tokio::signal::ctrl_c() => {}\n"
        "            _ = term.recv() => {}\n"
        "            _ = restart.recv() => {}\n"
        "        }\n",
        "        tokio::select! {\n"
        "            _ = tokio::signal::ctrl_c() => {}\n"
        "            _ = term.recv() => {}\n"
        "        }\n",
        label="unix 分支的 select",
    )
    must_replace(
        p,
        "        tokio::select! {\n"
        "            _ = tokio::signal::ctrl_c() => {}\n"
        "            _ = restart.recv() => {}\n"
        "        }\n",
        "        tokio::signal::ctrl_c().await.ok();\n",
        label="非 unix 分支的 select",
    )

    # ── 7. 模块头里的 AGENT2API_SELF_UPDATE 说明（两行：环境变量 + 它的续行）──
    must_cut_range(
        p,
        "//!   AGENT2API_SELF_UPDATE",
        "换文件后进程退出、由容器 restart 策略拉起）",
        label="模块头的自更新说明",
    )

    must_absent(p, "restart_rx", label="bin 里不应再有 restart_rx")
    must_absent(p, "set_restart_hook", label="bin 里不应再有重启钩子")
    must_absent(p, "AGENT2API_SELF_UPDATE", label="bin 里不应再有自更新开关")
    return "重启通道已摘除"
