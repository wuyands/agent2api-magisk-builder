# -*- coding: utf-8 -*-
"""把「Agent 配置」从外壳与手写脚本里摘干净。

三处：
  · `desktop-shell.tsx` —— 页面 section 的静态清单（每个 key 渲染一个
    `<section class="page" data-page=...>`，页面岛按这个挂载点找 DOM）。
  · `ui/app.js` —— `PAGES` 白名单、`PAGE_LABELS` 面包屑名、切页时拉数据的钩子。
  · `ui/sidebar-layout.js` —— 侧边栏菜单项与默认分组。

为什么要动 app.js / sidebar-layout.js：这两个不是构建产物，是手写的经典脚本
（`ui/` 目录里直接引用），不跟着改的话侧边栏还会出现一个点进去空白的菜单项。
"""

from base import must_absent, must_replace

TITLE = "外壳与手写脚本摘掉「Agent 配置」"

UI = "desktop-tauri/ui"
ISLANDS = "desktop-tauri/ui-islands/src"


def apply(root):
    shell = "%s/%s/desktop-shell.tsx" % (root, ISLANDS)
    app = "%s/%s/app.js" % (root, UI)
    sidebar = "%s/%s/sidebar-layout.js" % (root, UI)

    # ── 1. 页面 section 清单 ──
    must_replace(
        shell,
        "{['assistant', 'overview', 'accounts', 'checkin', 'routing', 'gateway', 'agent', 'tools', "
        "'proxies', 'keys', 'docs', 'logs', 'tasks', 'requests', 'plugins', 'settings'].map(key =>",
        "{['assistant', 'overview', 'accounts', 'checkin', 'routing', 'gateway', 'tools', "
        "'proxies', 'keys', 'docs', 'logs', 'tasks', 'requests', 'plugins', 'settings'].map(key =>",
        label="desktop-shell 的页面 section 清单",
    )

    # ── 2. app.js ──
    must_replace(
        app,
        "const PAGES = ['assistant', 'overview', 'accounts', 'checkin', 'routing', 'gateway', "
        "'agent', 'tools', 'proxies', 'keys', 'docs', 'logs', 'tasks', 'requests', 'plugins', 'settings'];",
        "const PAGES = ['assistant', 'overview', 'accounts', 'checkin', 'routing', 'gateway', "
        "'tools', 'proxies', 'keys', 'docs', 'logs', 'tasks', 'requests', 'plugins', 'settings'];",
        label="app.js 的 PAGES",
    )
    must_replace(
        app,
        "  agent: wbI18n.t('Agent 配置'),\n",
        "",
        label="app.js 的 PAGE_LABELS.agent",
    )
    must_replace(
        app,
        "  // Agent 页自持客户端清单与配置，切进去时拉一次最新（配置文件可能被\n"
        "  // 客户端自己改过、也可能刚在别的窗口里被别的工具改过）\n"
        "  if (page === 'agent') {\n"
        "    void window.wbAgentPanel?.load?.();\n"
        "  }\n",
        "",
        label="app.js 的 agent 切页钩子",
    )

    # ── 3. sidebar-layout.js ──
    must_replace(
        sidebar,
        "    { key: 'agent', label: wbI18n.t('Agent 配置'), icon: 'agent' },\n",
        "",
        label="sidebar-layout 的 agent 菜单项",
    )
    must_replace(
        sidebar,
        "    // 工具服务：给客户端装上的可选能力（网络搜索 / 视觉分析），排在客户端\n"
        "    // 配置之后、出网代理之前 —— 前者是「接哪些客户端」，这一项是「接了能用什么」。\n",
        "    // 工具服务：网关自带的可选能力（网络搜索 / 视觉分析），排在模型管理\n"
        "    // 之后、出网代理之前 —— 前者是「转发什么」，这一项是「转发之外还能用什么」。\n",
        label="sidebar-layout 的 tools 上方注释",
    )
    must_replace(
        sidebar,
        "          items: ['routing', 'gateway', 'agent', 'tools', 'proxies', 'keys', 'docs'] },",
        "          items: ['routing', 'gateway', 'tools', 'proxies', 'keys', 'docs'] },",
        label="sidebar-layout 的默认分组",
    )

    # 自检：三处都不该再有 agent 页的痕迹（`accounts-settings-dialog` 里的
    # `icon='agent'` 是图标名，不是页面键，不能连带删）
    for path, needle in [
        (shell, "'agent'"),
        (app, "'agent'"),
        (app, "wbAgentPanel"),
        (app, "Agent 配置"),
        (sidebar, "Agent 配置"),
    ]:
        must_absent(path, needle, label="%s 不应再有 %s" % (path, needle))

    return "外壳 + 2 个手写脚本"
