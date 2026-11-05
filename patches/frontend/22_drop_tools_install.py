# -*- coding: utf-8 -*-
"""工具服务页：删掉「本机接入」。

「本机接入」= 网关把 Skill / MCP 配置**写进本机各 AI 客户端的目录**，并探测
哪些客户端装在哪。这一整块在安卓上不成立：网关是 Magisk 模块里的守护进程，
没有、也不该有其它应用的私有目录写权限。

保留的是「详情」页要的那一份**纯元数据**：`GET /api/tools/install-info` 仍然
由后端提供（Rust 侧 05 补丁保留了精简版），前端照旧读它来显示 MCP 地址与
Skill 变体说明 —— 只是不再有「装到本机」这个动作。
"""

from base import must_absent, must_delete_file, must_present, must_replace

TITLE = "工具服务页删掉「本机接入」"

ISLANDS = "desktop-tauri/ui-islands/src/islands"


def apply(root):
    base = "%s/%s" % (root, ISLANDS)
    page = "%s/tools-page.tsx" % base
    data = "%s/tools-data.ts" % base
    detail = "%s/tools-detail.tsx" % base

    # ── 1. 页面：去掉弹窗、目标清单、「客户端环境」按钮与本机接入列 ──
    must_replace(
        page,
        "import { ToolDetail } from './tools-detail'\n"
        "import { ToolInstallDialog, ToolUninstallDialog } from './tools-install'\n"
        "import {\n"
        "  PROTOCOL_DESC, PROTOCOL_LABELS, SERVICE_DESC, SERVICE_NAME, fetchInstallTargets, fetchServices,\n"
        "  isDesktopShell, patchServer, type InstallTarget, type ToolProtocol, type ToolService,\n"
        "} from './tools-data'\n",
        "import { ToolDetail } from './tools-detail'\n"
        "import {\n"
        "  PROTOCOL_DESC, PROTOCOL_LABELS, SERVICE_DESC, SERVICE_NAME, fetchServices,\n"
        "  patchServer, type ToolProtocol, type ToolService,\n"
        "} from './tools-data'\n",
        label="tools-page 的导入",
    )

    must_replace(
        page,
        "  const desktop = isDesktopShell()\n"
        "  const [services, setServices] = React.useState<ToolService[]>([])\n"
        "  const [targets, setTargets] = React.useState<Record<string, InstallTarget[]>>({})\n",
        "  const [services, setServices] = React.useState<ToolService[]>([])\n",
        label="tools-page 的目标状态",
    )

    must_replace(
        page,
        "  const [detail, setDetail] = React.useState<ToolService | null>(null)\n"
        "  const [install, setInstall] = React.useState<{ service: ToolService; mode: 'skill' | 'mcp' } | null>(null)\n"
        "  const [uninstall, setUninstall] = React.useState<{ service: ToolService; mode: 'skill' | 'mcp' } | null>(null)\n",
        "  const [detail, setDetail] = React.useState<ToolService | null>(null)\n",
        label="tools-page 的安装弹窗状态",
    )

    must_replace(
        page,
        "      setServices(visibleRows)\n"
        "      if (desktop) void loadTargets(visibleRows)\n",
        "      setServices(visibleRows)\n",
        label="tools-page 的 loadTargets 调用",
    )

    must_replace(
        page,
        "  }, [desktop])\n",
        "  }, [])\n",
        label="tools-page 的 useCallback 依赖",
    )

    # loadTargets 整个函数体（从声明到收尾大括号 + 空行）
    must_replace(
        page,
        "  const loadTargets = async (rows: ToolService[]) => {\n"
        "    const entries = await Promise.all(rows.filter(row => row.protocol !== 'api').map(async row => {\n"
        "      try {\n"
        "        const result = await fetchInstallTargets(row.id, row.protocol === 'skill' ? 'skill' : 'mcp')\n"
        "        return [row.key, result.targets || []] as const\n"
        "      } catch {\n"
        "        return [row.key, []] as const\n"
        "      }\n"
        "    }))\n"
        "    setTargets(Object.fromEntries(entries))\n"
        "  }\n"
        "\n",
        "",
        label="tools-page 的 loadTargets",
    )

    must_replace(
        page,
        "        <p className='ml-3 text-xs text-subtle'>{t('管理可供客户端安装和运行的工具服务，并配置上游提供商与能力。')}</p>\n"
        "        {desktop ? <Button size='sm' variant='outline' className='ml-auto' onClick={() => (window as unknown as { wbApp?: { showPage?: (page: string) => void } }).wbApp?.showPage?.('agent')}>{t('客户端环境')}</Button> : null}\n",
        "        <p className='ml-3 text-xs text-subtle'>{t('管理网关对外提供的工具服务，并配置上游提供商与能力。')}</p>\n",
        label="tools-page 的页头",
    )

    must_replace(
        page,
        "                <TableHead>{t('操作')}</TableHead>\n"
        "                {desktop ? <TableHead>{t('本机接入')}</TableHead> : null}\n",
        "                <TableHead>{t('操作')}</TableHead>\n",
        label="tools-page 的本机接入表头",
    )

    must_replace(
        page,
        "                {visible.map(service => {\n"
        "                  const serviceTargets = targets[service.key] || []\n"
        "                  const installed = serviceTargets.filter(target => target.installed).length\n"
        "                  return <TableRow key={service.key}>\n",
        "                {visible.map(service => {\n"
        "                  return <TableRow key={service.key}>\n",
        label="tools-page 的行前导计算",
    )

    must_replace(
        page,
        "                    <TableCell><Button size='sm' variant='ghost' onClick={() => setDetail(service)}>{t('详情')}</Button></TableCell>\n"
        "                    {desktop ? <TableCell>\n"
        "                      <div className='flex flex-wrap gap-1.5'>\n"
        "                        <Button size='sm' variant='outline' disabled={!service.enabled || toggling === service.key}\n"
        "                          onClick={() => setInstall({ service, mode: service.protocol === 'mcp' ? 'mcp' : 'skill' })}>\n"
        "                          {installed > 0 ? t('更新') : t('安装')}\n"
        "                        </Button>\n"
        "                        <Button size='sm' variant='ghost' disabled={!installed} onClick={() => setUninstall({ service, mode: service.protocol === 'mcp' ? 'mcp' : 'skill' })}>{t('卸载')}</Button>\n"
        "                        {installed > 0 ? <span className='self-center text-[11px] text-subtle' title={t('已接入 {count} 个目标', { count: installed })}>{installed}</span> : null}\n"
        "                      </div>\n"
        "                    </TableCell> : null}\n",
        "                    <TableCell><Button size='sm' variant='ghost' onClick={() => setDetail(service)}>{t('详情')}</Button></TableCell>\n",
        label="tools-page 的本机接入单元格",
    )

    must_replace(
        page,
        "    </Card>\n"
        "\n"
        "    {install && <ToolInstallDialog service={install.service} mode={install.mode}\n"
        "      onClose={() => setInstall(null)}\n"
        "      onDone={() => { void load(); setInstall(current => current ? { ...current } : null) }} />}\n"
        "    {uninstall && <ToolUninstallDialog service={uninstall.service} mode={uninstall.mode}\n"
        "      onClose={() => setUninstall(null)}\n"
        "      onDone={() => { void load(); setUninstall(current => current ? { ...current } : null) }} />}\n"
        "  </div>\n",
        "    </Card>\n"
        "  </div>\n",
        label="tools-page 的安装弹窗渲染",
    )

    # ── 2. 数据层：删掉 4 个写客户端目录的接口与 3 个配套类型 ──
    must_replace(
        data,
        "export type InstallTarget = {\n"
        "  key: string\n"
        "  label: string\n"
        "  path: string\n"
        "  detected: boolean\n"
        "  installed: boolean\n"
        "}\n"
        "\n"
        "export type InstallOutcome = {\n"
        "  clientId: string\n"
        "  label: string\n"
        "  ok: boolean\n"
        "  path: string\n"
        "  error: string | null\n"
        "}\n"
        "\n"
        "export type ApiKeyOption = { id: string; name: string; masked: string }\n"
        "\n",
        "",
        label="tools-data 的三个安装类型",
    )

    must_replace(
        data,
        "export const fetchInstallTargets = (service: ToolServiceId, protocol: 'skill' | 'mcp'): Promise<{ targets: InstallTarget[] }> =>\n"
        "  callJson('GET', `/api/tools/install-targets?service=${encodeURIComponent(service)}&protocol=${protocol}`)\n"
        "\n"
        "export const fetchApiKeys = (): Promise<{ keys: ApiKeyOption[] }> => callJson('GET', '/api/tools/api-keys')\n"
        "\n"
        "export const installSkill = (body: { variant: string; api_key_id: string; clients: string[] }) =>\n"
        "  callJson<{ results: InstallOutcome[] }>('POST', '/api/tools/install-skill', body)\n"
        "\n"
        "export const installMcp = (body: { service_id: string; mode: string; api_key_id: string; clients: string[] }) =>\n"
        "  callJson<{ results: InstallOutcome[] }>('POST', '/api/tools/install-mcp', body)\n"
        "\n"
        "export const uninstallSkill = (body: { service_id: string; clients: string[] }) =>\n"
        "  callJson<{ results: InstallOutcome[] }>('POST', '/api/tools/uninstall-skill', body)\n"
        "\n"
        "export const uninstallMcp = (body: { service_id: string; clients: string[] }) =>\n"
        "  callJson<{ results: InstallOutcome[] }>('POST', '/api/tools/uninstall-mcp', body)\n"
        "\n",
        "",
        label="tools-data 的四个写客户端目录接口",
    )

    must_replace(
        data,
        "  mcp: { server_name: string; url: string; tools: string[]; bridge_url: string }\n",
        "  mcp: { server_name: string; url: string; tools: string[] }\n",
        label="tools-data 的 InstallInfo.mcp.bridge_url",
    )

    # ── 3. 详情页：本机桥接脚本那个字段没了 ──
    must_absent(detail, "bridge_url", label="tools-detail 不该再提 bridge_url")

    # ── 4. 两个弹窗文件整体删掉 ──
    must_delete_file("%s/tools-install.tsx" % base)

    # 自检
    for needle in ["install-targets", "install-skill", "install-mcp", "uninstall-skill", "uninstall-mcp", "本机接入", "客户端环境"]:
        must_absent(page, needle, label="tools-page 不应再有 %s" % needle)
    for needle in ["install-targets", "install-skill", "install-mcp", "uninstall-skill", "uninstall-mcp", "InstallTarget", "InstallOutcome", "ApiKeyOption"]:
        must_absent(data, needle, label="tools-data 不应再有 %s" % needle)
    # install-info 必须留着 —— 详情页靠它显示 MCP 地址
    must_present(data, "export const fetchInstallInfo", label="tools-data 的 fetchInstallInfo")
    must_present(detail, "fetchInstallInfo", label="tools-detail 仍在读 install-info")

    return "工具服务页 + 数据层 + 删 1 个弹窗文件"
