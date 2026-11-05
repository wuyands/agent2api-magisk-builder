# -*- coding: utf-8 -*-
"""删掉「Agent 配置」页（本机 AI 客户端配置接管）。

为什么整页删而不是隐藏：
  这一页的所有能力都建立在「网关和 AI 客户端跑在同一台机器上、能读到客户端
  的配置文件路径」这个前提上。安卓网关是个 Magisk 模块，客户端要么不在这个
  系统里、要么它的配置目录对一个沙箱里的守护进程既没有读权限也没有写权限。
  留着只会是「探测不到任何客户端」的永久空态 —— 那比没有这一页更难解释。

为什么删得掉：
  `island-registry.ts` 用 `import.meta.glob('./islands/*.tsx')` 自动收集页面岛，
  删掉文件即不再打包；`ui-shared/agent-resources*` 是**共用**的（mobile 端也在
  引），所以留着不动 —— 它们不参与桌面端构建，删了反而让 mobile 那一侧悬空。
"""

from base import must_delete_file, must_present

TITLE = "删除「Agent 配置」页的全部实现"

SRC = "desktop-tauri/ui-islands/src/islands"

# 这一页的 13 个文件：页面本体 + 状态机 + 各家客户端的表单/预览/编辑器。
# 名字全部以 agent- 开头，且它们之间只互相 import（外部零引用，见补丁说明）。
FILES = [
    "agent-catalog.ts",
    "agent-editor.tsx",
    "agent-fields.tsx",
    "agent-model-fields.tsx",
    "agent-model.ts",
    "agent-page.tsx",
    "agent-path-dialog.tsx",
    "agent-preview.tsx",
    "agent-profile-dialog.tsx",
    "agent-quick-connect.tsx",
    "agent-quick-model.ts",
    "agent-state.ts",
    "agent-types.ts",
]


def apply(root):
    islands = "%s/%s" % (root, SRC)

    # 先确认这一页还在 —— 上游哪天把它挪走或改名，这里要立刻知道。
    must_present("%s/agent-page.tsx" % islands, "export function AgentPage()", label="Agent 页入口")

    for name in FILES:
        must_delete_file("%s/%s" % (islands, name))

    return "删除 %d 个文件" % len(FILES)
