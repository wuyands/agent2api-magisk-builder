# -*- coding: utf-8 -*-
"""摘掉「软件更新」整条前端链路。

## 为什么整条删

安卓模块的二进制由 Magisk 整包替换 —— 面板里那套「检查 → 下载 → 安装 → 重启」
在手机上没有可执行对象：安装动作要写 `/data/adb/modules/agent2api`，那是
`magisk --install-module` 的活；`core::update::selfupdate` 在 Rust 侧已经换成
恒 `false` 的桩。留着面板只会让人点到一个回 404 的按钮。

## 删哪些

* 七个岛：`update-panel` / `update-required` / `update-modal` / `update-settings` /
  `update-systemd` / `update-qq-group` / `update-support-dialog`。
  实测 `grep -rn "from './update-"`：这七个之间互相引用成闭环，唯一入口是
  `update-panel.tsx` 自己 `mountOnPage('about', ...)` 挂到设置页的 about 面板上，
  **没有任何模块 import 它**。所以整组删掉不会留下悬空 import。
* `app.js` 里的更新提示与轮询（`lastUpdateInfo` / `seenUpdateVersion` /
  `syncUpdateBadge` / `updateUpdateBadge` / `pollUpdateStatus` / 导出表那一项 /
  DOMContentLoaded 里的 `syncUpdateCache`）+ 三颗角标的相关注释。
  `navBadgesReady = true;` **要留**：它是另外两颗角标（请求 / 日志）的前置，
  位置也必须在所有角标状态声明之后（TDZ）。
* 设置页的 `about` 分类与它的挂载 pane。

## 为什么留着 update-shared.ts 与 update-github-settings.tsx

`update-shared.ts` 的 `openExternal` / `handleExternalClick` / `markdownHtml` 被
`plugins-notes`、`proxies-dialogs`、`system-info-pane`、`tools-config` 四个无关的岛
在用；`update-github-settings.tsx` 被 `plugins-settings.tsx` 用作出网与 GitHub 令牌
设置（术语叫「更新通道」，但指的是**插件**更新）。两者都保留，其中纯软件更新
专用的导出留成死代码 —— 它们不影响 typecheck，而删它们要动 516 行文件的内部
依赖，收益为零。
"""

from base import (
    must_absent,
    must_cut_range,
    must_delete_file,
    must_present,
    must_replace,
)

TITLE = "设置页摘掉「软件更新」分类与整套面板"

ISLANDS = "desktop-tauri/ui-islands/src/islands"
UI = "desktop-tauri/ui"

# 七个互相引用成闭环、且没有外部 import 的岛
FILES = [
    ISLANDS + "/update-panel.tsx",
    ISLANDS + "/update-required.tsx",
    ISLANDS + "/update-modal.tsx",
    ISLANDS + "/update-settings.tsx",
    ISLANDS + "/update-systemd.ts",
    ISLANDS + "/update-qq-group.tsx",
    ISLANDS + "/update-support-dialog.tsx",
]


def apply(root):
    APP = root + "/" + UI + "/app.js"
    SHELL = root + "/desktop-tauri/ui-islands/src/desktop-shell.tsx"
    MODEL = root + "/" + ISLANDS + "/settings-model.ts"
    PAGE = root + "/" + ISLANDS + "/settings-page.tsx"
    STATE = root + "/" + ISLANDS + "/settings-state.ts"

    # ── 0. 删之前先确认这七个文件确实是我们要删的那一版 ──────────────
    must_present(root + "/" + FILES[0], "const PANE_SELECTOR = '.settings-pane[data-cat=\"about\"]'")
    must_present(root + "/" + FILES[0], "window.wbUpdatePanel = {")
    must_present(root + "/" + FILES[1], "function RequiredUpdate()")

    # ── 1. app.js：更新提示整段 ──────────────────────────────────
    # 1a 段标题 + 两个模块级变量（`navBadgesReady` 的文档块要留，所以只切到这里）
    must_replace(
        APP,
        "// ─── 新版本可用提示 ───────────────────────────\n"
        "\n"
        "/** 最近一次检查结果。存下来是为了换页时能重画提示（检查本身只在启动与手动触发时跑） */\n"
        "let lastUpdateInfo = null;\n"
        "/**\n"
        " * 已经看过提示的版本号。看过一次就没必要每次换页再闪一遍 ——\n"
        " * 与日志未读徽标的处理同一个取向（不打扰）。存版本号而不是布尔值：\n"
        " * 之后又发了更新的版本，提示该重新出现。\n"
        " */\n"
        "let seenUpdateVersion = '';\n"
        "\n",
        "",
        label="app.js：更新提示段的段标题与两个变量",
    )

    # 1b syncUpdateBadge + updateUpdateBadge 两个函数（含文档注释）
    must_cut_range(
        APP,
        " * 按当前状态重画「设置」导航项上的更新提示。",
        "  window.wbUpdatePanel?.showUpdateModal?.(info);",
        label="app.js：syncUpdateBadge / updateUpdateBadge",
        tail=1,  # updateUpdateBadge 的收尾大括号
    )
    # 上一步留下的孤立 `/**`（它的下一行就是「渲染：网关」分节）
    must_replace(
        APP,
        "/**\n\n// ─── 渲染：网关 / 模型 / 配置 ──────────────────",
        "// ─── 渲染：网关 / 模型 / 配置 ──────────────────",
        label="app.js：syncUpdateBadge 文档注释的孤立开头",
    )

    # 1c 三处 `syncUpdateBadge()` 调用（函数已不存在，调用点必须一起走）
    must_replace(
        APP,
        "  paintLogsBadgeFromMemory();\n"
        "  syncUpdateBadge();\n"
        "}\n",
        "  paintLogsBadgeFromMemory();\n"
        "}\n",
        label="app.js：syncNavBadges 里的调用",
    )
    must_replace(
        APP,
        "  // 导航项上的内容随页面变：日志未读徽标交给日志面板，更新提示在这里重画\n"
        "  // （校验更新提示的可见性与所在页面有关，见 syncUpdateBadge）\n"
        "  syncUpdateBadge();\n",
        "  // 导航项上的内容随页面变：日志未读徽标交给日志面板重画\n",
        label="app.js：showPage 里的调用",
    )

    # 1d 导出表：软件更新面板的回调出口
    must_replace(
        APP,
        "  // 软件更新面板在每次检查结束后回调它，把「有新版本」翻译成导航上的提示\n"
        "  updateUpdateBadge,\n",
        "",
        label="app.js：导出表里的 updateUpdateBadge",
    )

    # 1e DOMContentLoaded：面板预热那一行 + 上方「启动即铺一次更新状态」整段文档
    must_cut_range(
        APP,
        " * 启动即把更新状态铺一次：读**后端缓存**里的最近一次检查结果",
        " * 面板的 load() 同样只读缓存，所以这里这一下不会和它重复请求。",
        label="app.js：启动预热更新状态的文档注释",
        tail=1,  # 收尾 ` */`
    )
    must_replace(
        APP,
        "/**\ndocument.addEventListener('DOMContentLoaded'",
        "document.addEventListener('DOMContentLoaded'",
        label="app.js：启动预热文档注释的孤立开头",
    )
    must_replace(
        APP,
        "  // 以下三项都不影响当前页首帧：更新徽标读的是后端缓存，插件页菜单晚半秒出现\n"
        "  // 也不会挡住操作，侧边栏布局是跨设备同步。统一等首屏画完再做。\n"
        "  afterFirstPaint(() => {\n"
        "    void window.wbUpdatePanel?.syncFromCache?.();\n",
        "  // 插件页菜单晚半秒出现不影响操作，侧边栏布局是跨设备同步，统一等首屏画完再做。\n"
        "  afterFirstPaint(() => {\n",
        label="app.js：DOMContentLoaded 里的面板预热",
    )

    # 1f 文末的轮询（自适应节奏、读后端缓存）整段删掉
    must_cut_range(
        APP,
        "// 「软件版本检查」结果的轮询：读**后端缓存**，不自己打 GitHub。",
        # 结束标记必须唯一：`setTimeout(pollUpdateStatus, updatePollDelay);` 在函数体
        # 第 2 行（settle 的闭包）里也出现过，逐行子串匹配会提前收刀。
        "  }).finally(settle);",
        label="app.js：pollUpdateStatus 轮询整段",
        tail=3,  # 收掉函数右括号、空行、文末那一下启动调用
    )
    must_absent(APP, "pollUpdateStatus")
    must_absent(APP, "getUpdateStatus")
    must_absent(APP, "wbUpdatePanel")
    must_absent(APP, "nav-count-update")

    # ── 2. app.js 注释里的「三颗角标」改「两颗」 ─────────────────
    must_replace(
        APP,
        " * 「哪个节点对应哪个菜单」的映射。三颗角标是**按 id 重建**的，所以重画之后",
        " * 「哪个节点对应哪个菜单」的映射。两颗角标是**按 id 重建**的，所以重画之后",
        label="app.js：整块重画说明",
    )
    must_replace(
        APP,
        " *   · 角标 id 固定三颗：nav-count-requests / -logs / -update；",
        " *   · 角标 id 固定两颗：nav-count-requests / -logs；",
        label="app.js：导航契约说明",
    )
    must_replace(
        APP,
        " * 三颗角标的数据都由轮询维护在模块级变量里（runningRequests / unreadFailures /\n"
        " * lastUpdateInfo / 未读日志水位），重画把 DOM 换掉之后新节点是「隐藏 + 0」，",
        " * 两颗角标的数据都由轮询维护在模块级变量里（runningRequests / unreadFailures /\n"
        " * 未读日志水位），重画把 DOM 换掉之后新节点是「隐藏 + 0」，",
        label="app.js：syncNavBadges 文档",
    )
    must_replace(
        APP,
        " * 三颗角标的内存值都初始化完了 —— 从这里开始 syncNavBadges 才有意义。",
        " * 角标的内存值都初始化完了 —— 从这里开始 syncNavBadges 才有意义。",
        label="app.js：navBadgesReady 文档",
    )
    # 这一段置位必须留：另外两颗角标依赖它，位置也必须在所有角标状态声明之后
    must_present(APP, "navBadgesReady = true;")

    # ── 3. 外壳：设置项上的「新」角标 ───────────────────────────
    must_replace(
        SHELL,
        "        const badgeId = menu.key === 'requests' ? 'nav-count-requests' "
        ": menu.key === 'logs' ? 'nav-count-logs' : menu.key === 'settings' "
        "? 'nav-count-update' : ''",
        "        const badgeId = menu.key === 'requests' ? 'nav-count-requests' "
        ": menu.key === 'logs' ? 'nav-count-logs' : ''",
        label="desktop-shell：nav-count-update 三元",
    )
    must_replace(
        SHELL,
        "{menu.key === 'settings' ? t('新') : '0'}",
        "0",
        label="desktop-shell：角标初值",
    )
    must_absent(SHELL, "nav-count-update")

    # ── 4. settings-model.ts：分类表与桥类型 ────────────────────
    must_replace(
        MODEL,
        "  /** 软件更新面板的岛（update-panel.tsx）：切到设置页时让它自己刷新一次 */\n"
        "  wbUpdatePanel?: { load?: () => Promise<void> | void }\n",
        "",
        label="settings-model：wbUpdatePanel 桥类型",
    )
    must_replace(
        MODEL,
        " * 「反馈与需求」是纯跳转面板（三个 GitHub issue 表单入口，见 settings-page 的\n"
        " * FeedbackPane），排在「更新」上面 —— 都是「对外」的两栏，挨着放。",
        " * 「反馈与需求」是纯跳转面板（三个 GitHub issue 表单入口，见 settings-page 的\n"
        " * FeedbackPane），排在最后一栏 —— 「对外」的那一栏。",
        label="settings-model：分类顺序说明",
    )
    must_replace(
        MODEL,
        " *\n"
        " * 「更新」（原「关于」）**id 保持 `about` 不变**：它同时是 update-panel.tsx 的挂载点\n"
        " * 选择器（`.settings-pane[data-cat=\"about\"]`）与用户 localStorage 里存着的分类值，\n"
        " * 改名会让两者当场失配 —— 用户看到的只是标签，id 是内部契约。\n",
        "",
        label="settings-model：about 分类的说明段",
    )
    must_replace(
        MODEL,
        "  { id: 'about', label: t('更新'), icon: 'download' },\n",
        "",
        label="settings-model：about 分类项",
    )
    must_absent(MODEL, "wbUpdatePanel")
    must_absent(MODEL, "id: 'about'")

    # ── 5. settings-page.tsx：about 面板与相关注释 ─────────────
    must_replace(
        PAGE,
        " * app.js:135 load()、upgrade-panel.js:74 load()、islands/update-panel.tsx:972 showCategory('about')。",
        " * app.js:135 load()、upgrade-panel.js:74 load()。",
        label="settings-page：模块头的调用点清单",
    )
    must_cut_range(
        PAGE,
        " * ── ⚠ 「更新」分类（原「关于」）的面板不归本文件 ───────────",
        " * 那个岛的面板跟着显示，与旧实现命令式切 class 等价。",
        label="settings-page：「更新」分类的协作说明",
        tail=1,  # 该段收尾的 ` *`
    )
    must_replace(
        PAGE,
        "        {/*\n"
        "          「更新」的面板（原「关于」，id 仍是 about）由另一个岛（update-panel.tsx）接管：\n"
        "          它按这个选择器找挂载点，找到就把 React root 建在这个 div 上。所以这里必须是\n"
        "          **空的**、且永远保持同一个元素（不给 children、不改它在兄弟中的位置、不条件渲染）——\n"
        "          React 对没有 children 的宿主元素不会去动它的 DOM 子树，那个岛的渲染结果才留得住。\n"
        "          显隐照旧：className 上的 active 由本文件按当前分类切。\n"
        "        */}\n"
        "        <div className={paneClass('about')} data-cat='about' />\n",
        "",
        label="settings-page：about 面板与挂载说明",
    )
    must_replace(
        PAGE,
        " * ── 为什么必须 flushSync ──────────────────────\n"
        " * `.settings-pane[data-cat=\"about\"]` 是 update-panel.tsx 的挂载点，它在**自己的模块加载期**\n"
        " * 就 `document.querySelector` 这个选择器，找到才建 root。React 19 的 `createRoot().render()`\n"
        " * 是并发调度，提交可能落在下一个宏任务 —— 那一刻这个 pane 还没进 DOM，update-panel 只会\n"
        " * 退化成等 DOMContentLoaded，而那时它早已过了注册窗口，「设置 → 更新」会整块空白。\n"
        " * 两个岛的求值顺序由 glob 的文件名字典序决定（settings-page.tsx 排在 update-panel.tsx 前），\n"
        " * 所以这里同步提交之后，它一定能查到。\n",
        " * ── 为什么必须 flushSync ──────────────────────\n"
        " * `.settings-pane[data-cat=\"system\"]` 由另一个岛（system-info-pane.tsx）接管，它在挂载时\n"
        " * `document.querySelector` 这个选择器。React 19 的 `createRoot().render()` 是并发调度，\n"
        " * 提交可能落在下一个宏任务 —— 同步提交之后那个岛才一定查得到挂载点。\n",
        label="settings-page：mount 的 flushSync 说明",
    )
    must_replace(
        PAGE,
        "     * 调用点：app.js:135 切到设置页时 load()；upgrade-panel.js:74 迁移完成后 load()；\n"
        "     * update-panel.tsx:972 的「去更新」showCategory('about')。\n",
        "     * 调用点：app.js:135 切到设置页时 load()；upgrade-panel.js:74 迁移完成后 load()。\n",
        label="settings-page：对外契约的调用点注释",
    )
    must_absent(PAGE, "update-panel")
    must_absent(PAGE, "data-cat='about'")

    # ── 6. settings-state.ts：切进设置页时的预热调用 ────────────
    must_replace(
        STATE,
        "    // 软件更新面板是另一个岛（update-panel.tsx），切进设置页时让它自己刷新一次\n"
        "    shared().wbUpdatePanel?.load?.(),\n",
        "",
        label="settings-state：wbUpdatePanel 预热",
    )
    must_replace(
        STATE,
        " * 刻意**不写** localStorage：update-panel 的「去更新」深链会调它切到「更新」，\n"
        " * 那不该改用户手点的默认分类（写偏好的是 selectCategory）。",
        " * 刻意**不写** localStorage：改偏好的是 selectCategory，这个函数只负责这一次切换，\n"
        " * 那不该改用户手点的默认分类。",
        label="settings-state：showCategory 的说明",
    )
    must_replace(
        STATE,
        " * ── 状态放模块级快照 + useSyncExternalStore（照 update-panel / models-panel-state）──",
        " * ── 状态放模块级快照 + useSyncExternalStore（照 models-panel-state）──",
        label="settings-state：模块头的写法出处",
    )
    must_absent(STATE, "wbUpdatePanel")

    # ── 7. 删文件（放最后：上面的锚点都从这些文件之外取，删早了也不影响，
    #        但放最后能让失败时的报错更好定位——前六步都是「内容变了」而非「文件没了」）
    for path in FILES:
        must_delete_file(root + "/" + path)

    return "设置页分类 + app.js 提示与轮询 + 删 7 个岛"
