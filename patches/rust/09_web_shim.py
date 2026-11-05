# -*- coding: utf-8 -*-
"""web_shim.rs：删掉网页端桥接里那批指向已裁接口的方法。

网页端没有 Tauri 壳，`@tauri-apps/api` 的 `invoke` 由这个文件顶替（它就是
`window.__TAURI_INTERNALS__` 的那份 shim）。桥接方法名必须与桌面壳 `bridge.rs`
一一对应 —— 上游为此在注释里反复强调「只加一边时另一形态下的页面会报桥接方法
缺失」。所以这里删的是**两侧都废掉的功能**，不是单边偷懒：

  · 软件更新（`check_update` / 下载三件套 / 出网线路 / 令牌 / beta / 通道 /
    安装程序 / 容器内更新）—— 后端 `/api/update/*` 整条路由都删了，留着这些
    方法只会让界面拿到 404。
  · Agent 配置接管（`getAgents` 等 6 条）—— `api::agents` 整个模块删了。

**必须保留 `getSystemInfo`**：它夹在软件更新那一大块中间，但打的是
`/api/system-info`，是设置页「版本信息」的唯一来源，与更新无关。所以那一大块
要拆成两刀删，中间这段留下。
"""

from base import must_replace, must_absent, must_present

TITLE = "web_shim.rs：删掉已裁功能的桥接方法（保留 getSystemInfo）"

SRC = "desktop-tauri/src-tauri/server/src"
SHIM = SRC + "/web_shim.rs"

# ── 1. shellCommands 表里的软件更新三件套 ──
SHELL_UPDATE = """    check_update: function () {
      // 网页端没有「壳打包的版本号」这个概念：不带 current，服务端按自己的
      // 编译期版本比较（见 api/update 的 check 分支）。返回里带 selfUpdate /
      // serverAsset —— 面板据此决定显示「一键更新」还是手动升级命令。
      return call('GET', '/api/update/check');
    },
    get_update_status: function () { return call('GET', '/api/update/status'); },
    // 下载三件套：下载落在服务端的数据目录（/data/updates），进度由面板轮询。
    // 桌面端这三个走壳命令（壳要往后端转发），网页端直接打接口 —— 桥的两侧
    // 名字一致，面板代码不感知差异。
    download_update: function (args) {
      var payload = args || {};
      return call('POST', '/api/update/download', {
        url: String(payload.url || ''),
        name: payload.name != null ? String(payload.name) : '',
      });
    },
    update_progress: function () { return call('GET', '/api/update/progress'); },
    cancel_update: function () { return call('POST', '/api/update/cancel', {}); },
"""

# ── 2. 打开 release 页（网页端版 shim 里的壳命令名）──
SHELL_OPEN_RELEASE = """    open_release_page: function (args) {
      if (args && args.url) { try { window.open(args.url, '_blank'); } catch (e) { /* 无害 */ } }
      return Promise.resolve({ url: (args && args.url) || '' });
    },
"""

# ── 3. Agent 桥（6 条 + 3 行说明）──
AGENT_BRIDGE = """    // Agent（本机 AI 客户端的配置接管；与桌面壳 bridge.rs 的同名方法成对
    // 存在 —— 只加一边时另一形态下的页面会报「桥接方法缺失」。契约见
    // api::agents 的模块头：写操作都返回整份 {clients}，就地替换）
    getAgents: function () { return call('GET', '/api/agents'); },
    saveAgentProfiles: function (payload) { return call('POST', '/api/agents/profiles', payload || {}); },
    applyAgentProfile: function (payload) { return call('POST', '/api/agents/apply', payload || {}); },
    previewAgentProfile: function (payload) { return call('POST', '/api/agents/preview', payload || {}); },
    restoreAgentClient: function (payload) { return call('POST', '/api/agents/restore', payload || {}); },
    importAgentClient: function (payload) { return call('POST', '/api/agents/import', payload || {}); },
"""

# ── 4. 软件更新那一大块的前半截（getSystemInfo 之前）──
UPDATE_HEAD = """    // ── 软件更新（检查 / 下载 / 容器内更新；只有「跑安装程序」是桌面专有）──
    checkUpdate: function () { return invokeShell('check_update'); },
    getUpdateStatus: function () { return call('GET', '/api/update/status'); },
"""

# ── 5. 软件更新那一大块的后半截（getSystemInfo 之后，到 restartService 为止）──
UPDATE_TAIL_START = "    // 「软件更新」的出网线路（null = 直连）：与桌面 bridge 对齐，面板下拉读写"
UPDATE_TAIL_END = "    restartService: function () { return call('POST', '/api/update/restart', {}); },"

# ── 6. invokeShell 里为 run_installer 单开的那条文案（命令已不存在）──
INVOKE_TAIL_OLD = """    return Promise.reject(new Error(
      command === 'run_installer'
        ? '网页端不启动安装程序：容器内的更新请用「一键更新」（设置 → 软件更新）'
        : SHELL_UNAVAILABLE
    ));
"""
INVOKE_TAIL_NEW = """    return Promise.reject(new Error(SHELL_UNAVAILABLE));
"""


def _cut_between(path, start_marker, end_marker, label):
    """删掉 start_marker 所在行到 end_marker 所在行（含两端）。"""
    from base import must_cut_range

    return must_cut_range(path, start_marker, end_marker, label=label)


def apply(root):
    p = "%s/%s" % (root, SHIM)

    must_replace(p, SHELL_UPDATE, "", label="shellCommands 的软件更新三件套")
    must_replace(p, SHELL_OPEN_RELEASE, "", label="shellCommands 的 open_release_page")
    must_replace(p, AGENT_BRIDGE, "", label="Agent 桥的 6 条方法")
    must_replace(p, UPDATE_HEAD, "", label="软件更新的 checkUpdate / getUpdateStatus")
    _cut_between(p, UPDATE_TAIL_START, UPDATE_TAIL_END, "软件更新的出网线路与容器内更新")
    must_replace(p, INVOKE_TAIL_OLD, INVOKE_TAIL_NEW, label="invokeShell 的 run_installer 文案")

    # getSystemInfo 必须还在（它夹在删掉的两段中间）
    must_present(p, "    getSystemInfo: function (options) {", label="getSystemInfo 被误删")

    # 自检：这些字符串一个都不该剩下
    for gone in [
        "/api/update/",
        "invokeShell('check_update')",
        "invokeShell('download_update')",
        "invokeShell('update_progress')",
        "invokeShell('cancel_update')",
        "invokeShell('open_release_page')",
        "invokeShell('run_installer'",
        "/api/agents",
        "run_installer",
        "AGENT2API_SELF_UPDATE",
    ]:
        must_absent(p, gone, label="web_shim.rs 里不应再有 %s" % gone)

    return "删 6 块（含保留 getSystemInfo）"
