"""把「从 cc-switch 导入」整段从「添加账号」弹窗里摘掉。

─────────────────────────────────────────────────────────────
为什么删（而不是像上游那样只用 IMPORT_SEGMENT_ENABLED 收起）
─────────────────────────────────────────────────────────────
上游从 v3.3 起就把这个分段在界面上收起来了（`IMPORT_SEGMENT_ENABLED = false`），
但实现整块留着：`add-provider-import.tsx` 里还有 `GET /api/import/cc-switch`
的扫描调用，后端 `core::import_ccswitch` 也还在读本机的 cc-switch SQLite。

安卓移植里这条链路两头都不成立：

  · 后端 —— `import_ccswitch` 扫的是桌面客户端（cc-switch / Claude Code /
    Codex CLI）在本机的配置目录，沙箱守护进程读不到也不该读；
    所以 `core/import_ccswitch.rs` 与 `api/import_sources.rs` 已经删了，
    `/api/import/cc-switch` 路由一并撤掉（见 rust/01、rust/06）。
  · 前端 —— 路由没了，`request('GET', '/api/import/cc-switch')` 只会拿到 404，
    在界面上表现为「扫描失败」的空面板。

留着一个永远打不开的分段 + 一个永远 404 的请求没有意义，所以整段删干净：
删文件、删 `TYPE_IMPORT`、删 `IMPORT_SEGMENT_ENABLED`、删 `PickStep` 上那对
只为它存在的 `importing` / `importPanel` 属性。

`island-registry.ts` 用 `import.meta.glob('./islands/*.tsx')` 自动收集，
删 `.tsx` 就自然不再打包，不需要改注册表。
"""

from base import must_absent, must_delete_file, must_present, must_replace

TITLE = "「添加账号」弹窗摘掉 cc-switch 导入段"

# 被删的岛（唯一引用点是 add-account-modal.tsx，见文件头）
DROPPED = "desktop-tauri/ui-islands/src/islands/add-provider-import.tsx"

MODAL = "desktop-tauri/ui-islands/src/islands/add-account-modal.tsx"
PICK = "desktop-tauri/ui-islands/src/islands/add-provider-pick.tsx"


def apply(root):
    modal = root + "/" + MODAL
    pick = root + "/" + PICK
    dropped = root + "/" + DROPPED

    # ── 0. 删之前先确认这是我们要删的那一版 ──────────────────────
    must_present(dropped, "export function ImportPanel(")
    must_present(dropped, "export function ImportFootActions(")
    must_present(pick, "export const IMPORT_SEGMENT_ENABLED = false")
    must_present(pick, "export const TYPE_IMPORT: AccountType = 'import'")

    # ── 1. add-provider-pick.tsx：摘掉「导入」这一档本身 ─────────
    # 1a 类型联合去掉 'import'
    must_replace(
        pick,
        "export type AccountType = 'all' | 'proxy' | 'web' | 'preset' | 'custom' | 'import'",
        "export type AccountType = 'all' | 'proxy' | 'web' | 'preset' | 'custom'",
        label="add-provider-pick：AccountType 去掉 'import'",
    )
    # 1b 文件头注释里的分类清单
    must_replace(
        pick,
        "/** 第 1 步的账号类型：全部 / Agent / Web / API 模板 / 已建 API / 导入 */",
        "/** 第 1 步的账号类型：全部 / Agent / Web / API 模板 / 已建 API */",
        label="add-provider-pick：类型注释",
    )
    # 1c TYPE_IMPORT 常量
    must_replace(
        pick,
        "export const TYPE_CUSTOM: AccountType = 'custom'\n"
        "export const TYPE_IMPORT: AccountType = 'import'\n",
        "export const TYPE_CUSTOM: AccountType = 'custom'\n",
        label="add-provider-pick：TYPE_IMPORT",
    )
    # 1d IMPORT_SEGMENT_ENABLED 常量连同它的整段说明
    must_replace(
        pick,
        "/**\n"
        " * 「导入」分段是否露出。当前 **false**：这一屏还没做完整，先从界面上收起来。\n"
        " *\n"
        " * 收的是入口、不是实现 —— 导入面板、后端 `/api/import/cc-switch` 与配套 CSS\n"
        " * 全部原样留着（见 add-provider-import.tsx），等这一屏补齐把这里改回 true 即可。\n"
        " * 关掉之后：分段不生成 → 到不了 TYPE_IMPORT → 面板不挂载、底部「导入所选」\n"
        " * 也不会被点亮，走的就是「用户从没点过这个分段」那条路径。\n"
        " */\n"
        "export const IMPORT_SEGMENT_ENABLED = false\n"
        "\n",
        "",
        label="add-provider-pick：IMPORT_SEGMENT_ENABLED",
    )
    # 1e typeValueOf 里的分支
    must_replace(
        pick,
        "  if (IMPORT_SEGMENT_ENABLED && value === TYPE_IMPORT) return TYPE_IMPORT\n",
        "",
        label="add-provider-pick：typeValueOf 分支",
    )
    # 1f typeLabelOf 里的分支
    must_replace(
        pick,
        "  if (type === TYPE_IMPORT) return t('导入')\n",
        "",
        label="add-provider-pick：typeLabelOf 分支",
    )
    # 1g PickStep 的 props
    must_replace(
        pick,
        "  /** 导入段：卡片网格与搜索整块收起（导入面板占同一块区域） */\n"
        "  importing: boolean\n"
        "  /** 导入面板（分段收起时不存在）：与卡片网格互斥显隐，占同一块位置 */\n"
        "  importPanel?: React.ReactNode\n"
        "}",
        "}",
        label="add-provider-pick：PickStepProps 去掉 importing / importPanel",
    )
    # 1h 解构
    must_replace(
        pick,
        "  version,\n"
        "  importing,\n"
        "  importPanel,\n"
        "}: PickStepProps): React.ReactElement {",
        "  version,\n"
        "}: PickStepProps): React.ReactElement {",
        label="add-provider-pick：PickStep 解构",
    )
    # 1i 分段行上的隐藏样式（导入态不存在了）
    must_replace(
        pick,
        "      <div className='add-pick-row' style={importing ? { display: 'none' } : undefined}>",
        "      <div className='add-pick-row'>",
        label="add-provider-pick：分段行",
    )
    # 1j 分段选项末尾那一档
    must_replace(
        pick,
        "            { value: TYPE_CUSTOM, label: typeLabelOf(TYPE_CUSTOM) },\n"
        "            // 「导入」分段暂时收起（见 IMPORT_SEGMENT_ENABLED）：整段不生成\n"
        "            ...(IMPORT_SEGMENT_ENABLED ? [{ value: TYPE_IMPORT, label: typeLabelOf(TYPE_IMPORT) }] : []),\n",
        "            { value: TYPE_CUSTOM, label: typeLabelOf(TYPE_CUSTOM) },\n",
        label="add-provider-pick：分段选项",
    )
    # 1k 导入面板的插槽
    must_replace(
        pick,
        "      {/* 导入面板插在卡片网格的位置上（与网格互斥显隐），放在网格之前 ——\n"
        "          两屏内容同一块区域，滚动位置也就跟着换，不会串 */}\n"
        "      {importPanel}\n",
        "",
        label="add-provider-pick：importPanel 插槽",
    )
    # 1l 卡片网格上的隐藏样式
    must_replace(
        pick,
        "        aria-label={t('选择要添加账号的提供商')}\n"
        "        style={importing ? { display: 'none' } : undefined}\n"
        "      >",
        "        aria-label={t('选择要添加账号的提供商')}\n"
        "      >",
        label="add-provider-pick：卡片网格",
    )

    # ── 2. add-account-modal.tsx：摘掉导入段的接线 ───────────────
    # 2a 文件头提到的那份旧脚本
    must_replace(
        modal,
        " * ui/add-provider-import.js（导入段）、ui/add-custom-provider.js（自定义块）\n",
        " * ui/add-custom-provider.js（自定义块）\n",
        label="add-account-modal：文件头",
    )
    # 2b 导入语句
    must_replace(
        modal,
        "import { ImportFootActions, ImportPanel } from './add-provider-import'\n",
        "",
        label="add-account-modal：add-provider-import 的 import",
    )
    # 2c 从 add-provider-pick 引的两个符号
    must_replace(
        modal,
        "  IMPORT_SEGMENT_ENABLED,\n",
        "",
        label="add-account-modal：IMPORT_SEGMENT_ENABLED 引用",
    )
    must_replace(
        modal,
        "  TYPE_IMPORT,\n",
        "",
        label="add-account-modal：TYPE_IMPORT 引用",
    )
    # 2d importing 状态
    must_replace(
        modal,
        "  const importing = state.accountType === TYPE_IMPORT\n",
        "",
        label="add-account-modal：importing 状态",
    )
    # 2e PickStep 的两条属性
    must_replace(
        modal,
        "            version={version}\n"
        "            importing={importing}\n"
        "            importPanel={\n"
        "              IMPORT_SEGMENT_ENABLED ? <ImportPanel segmentOn={importing} /> : undefined\n"
        "            }\n",
        "            version={version}\n",
        label="add-account-modal：PickStep 属性",
    )
    # 2f 列表弹窗底部那条只为导入服务的操作条
    must_replace(
        modal,
        "        {/* 列表弹窗这条操作条只服务「留在第 1 步完成」的动作（导入段的「导入所选」）；\n"
        "            第 2 步的主按钮走下面那条，两条各归各的层级 */}\n"
        "        {IMPORT_SEGMENT_ENABLED && importing ? (\n"
        "          <DialogFooter>\n"
        "            <ImportFootActions />\n"
        "          </DialogFooter>\n"
        "        ) : null}\n"
        "\n",
        "",
        label="add-account-modal：导入操作条",
    )

    # ── 3. 删掉整份实现 ────────────────────────────────────────
    must_delete_file(dropped)

    # ── 4. 自检 ────────────────────────────────────────────────
    for path, label in ((pick, "add-provider-pick"), (modal, "add-account-modal")):
        for needle in ("TYPE_IMPORT", "IMPORT_SEGMENT_ENABLED", "importPanel", "importing"):
            must_absent(path, needle, label=label + " → " + needle)
        must_absent(path, "cc-switch", label=label + " → cc-switch")
        must_absent(path, "/api/import/", label=label + " → /api/import/")
    # DialogFooter 还有第 2 步那条在用，不能连它一起清掉
    must_present(modal, "className='acct-add-foot'")
    # PickStep 本身的其它属性还在
    must_present(pick, "  onPick: (id: string) => void\n")
    must_present(pick, "const GROUPED_TYPES: AccountType[] = [TYPE_PROXY, TYPE_WEB, TYPE_PRESET, TYPE_CUSTOM]")

    return "删 1 个岛 + 弹窗与分段各摘一段"
