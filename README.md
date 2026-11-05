# Agent2API Magisk 模块 · 云编译仓库

把 [aimod-cc/Agent2API](https://github.com/aimod-cc/Agent2API) 自动编成 **Magisk 模块 zip**，
装到 Android arm64 手机上跑一个本地网关。上游是桌面/服务器项目，这个仓库负责两件事：

1. **交叉编译** —— 用 NDK r27d 把网关与提供商插件编成 `aarch64-linux-android` 二进制，
   连同 Magisk 模块骨架打成可直接刷入的 zip。
2. **适配裁剪** —— 把在 Android 上没有意义的桌面功能摘掉（见下），让产物不留半截入口。
3. **每天跟上游** —— 定时检查上游与插件仓库的新版本，自动构建；成功才发 release，
   失败开 issue 附失败补丁名。

模块本身的行为（开机自启、看门狗、`ctl.sh` 控制、插件铺设/升级、卸载清理）由
`module/` 下的脚本决定，与上游版本无关。

---

## 为什么云编译

上游是 Tauri 桌面应用 + 一个独立 Rust 网关。手机要的是其中**网关那一个二进制**，
但源码里 `include_str!` 把前端产物（`ui/islands/ui.js`，2.3 MB）编进了二进制：

```rust
// desktop-tauri/src-tauri/server/src/server/api/plugin_theme.rs
const ISLANDS_JS: &str = include_str!("../../../../../ui/islands/ui.js");
```

所以**必须先构建前端、再编译 Rust**，顺序反了就是「编出来的包界面还是旧的」。
本仓库的流水线按这个顺序排（`build.yml` 的第 ⑤⑥ 步）。

---

## 仓库结构

```
module/                 Magisk 模块骨架（脚本手写，随仓库版本化）
  module.prop           id / name / version / versionCode（version 与 versionCode 由 CI 注入）
  customize.sh          安装期：打印说明、建数据目录
  service.sh            开机：等 boot_completed → plugin-setup → setsid 起看门狗
  watchdog.sh           看门狗：15 秒轮询网关，退避最长 300 秒，日志 2 MB 轮转
  ctl.sh               命令行控制：start/stop/restart/status/plugins/logs（含 action.sh 供 Magisk 用）
  plugin-setup.sh      首次开机把内置插件铺到 /data/adb/agent2api/plugins 并登记
  uninstall.sh         卸载：停进程、清数据目录
  META-INF/            刷入脚本
  webroot/index.html   KernelSU / APatch 的模块页
  ★ bin/ ui/ plugin-pack/ plugin-registry/ 由 CI 生成，git 里没有

patches/               断言式补丁（改上游源码，不改构建产物）
  base.py              原语：must_replace / must_cut_range / must_delete_file / must_present …
  apply.py             入口：按目录顺序跑，失败立即退出并打印定位
  rust/                01…10  后端裁剪
  frontend/            20…24  前端裁剪

scripts/               构建期脚本
  build.sh             交叉编译（NDK / target / 环境变量全在这里）
  prepare.py           生成 module.prop 版本、pack.json、插件注册表、铺 ui/ 与 bin/
  pack.py              打 zip（固定时间戳、可执行位、META-INF 排最前）
  verify.py            对 zip 做 9 组检查（不通过就不发 release）
  upstream.py          问 GitHub 要最新 tag，写 upstream.json

tests/test_patches.py  补丁引擎的单元测试（秒级，不需要上游源码）

.github/workflows/
  build.yml            可手动触发，也可被 daily-sync 复用（workflow_call）
  daily-sync.yml       每天 12:17（北京）检查上游 → 有新版本就构建 → 失败开 issue
```

---

## 裁掉了什么，为什么

上游的功能是按**桌面客户端**设计的。下面五块在 Android 上不是「不好用」，是
**没有作用对象**，留着只会让界面出现点不开的入口。

| 裁掉的东西 | 上游代码 | 为什么在手机上没意义 |
|---|---|---|
| **Agent 配置页** | `api/agents.rs`、`api/agent_resources.rs`、`core/agents/`（6000+ 行）、前端 13 个 `agent-*` 文件 | 它读写的是**本机桌面客户端**（Cursor / VSCode / Claude Code…）的配置文件。手机上那些客户端不存在；即便存在，Magisk 模块跑在独立的守护进程里，摸不到别的 App 的私有目录。 |
| **工具服务的「本机接入」** | `api/tools.rs` 的 install/uninstall 六条、`core/tool_services/{install,bridge}.rs`、前端「安装 / 更新 / 卸载」列 | 把 MCP 配置写进 Claude Desktop / Cursor 的配置文件，并下载一个本地桥接脚本。同样是「往桌面客户端的配置目录写文件」。**工具服务本体（网络搜索 / 视觉分析 / 三协议 / 密钥管理）全部保留。** |
| **软件更新 / 自更新** | `api/update.rs`、`core/update/selfupdate.rs`、前端整套 update 面板（7 个岛）、`app.js` 的更新轮询 | 模块的二进制归 Magisk 管：升级就是刷一个新 zip。让 App 自己去 GitHub 下 tar.gz、解开、替换自己的可执行文件，在 `/data/adb/modules` 下既不必要也不安全（替换完还得重启进程，Magisk 那边并不知道）。**更新「检查」保留** —— 插件市场要靠它跟随渠道。 |
| **Clash Verge 配置读取** | `core/clash.rs` | 读的是 Clash Verge（桌面代理软件）落在用户目录里的 YAML。手机上那个路径永远是空的。改成恒返回「不可用」的桩，形状不变，调用方不用改。 |
| **cc-switch 导入** | `api/import_sources.rs`、`core/import_ccswitch.rs`、前端 `add-provider-import.tsx` | 从 cc-switch 的配置文件里扫出账号再导进来。上游自己已经把这个入口在界面上关掉了（`IMPORT_SEGMENT_ENABLED = false`），后端路由跟着一起删干净。 |

**没裁的**：模型转发、账号与签到、路由与网关、代理、密钥、API 文档、日志、定时任务、请求记录、插件市场、设置（除「更新」分类）——这些在手机上都成立。

### 补丁怎么写

不按行号删，按**文本锚点**删，并且每次都要求「恰好命中 N 次」：

```python
must_replace(path, "旧的完整文本", "新的完整文本")        # 期望 1 次，多一次少一次都失败
must_cut_range(path, "起始标记", "结束标记", tail=1)       # 删一段，tail 是结束标记后连带几行
must_delete_file(path)                                    # 删文件，不存在就失败
must_absent(path, "某个字符串")                            # 改完自检：这东西不该还在
must_present(path, "某个字符串")                           # 改完自检：这东西必须还在
```

**为什么不「尽力而为」**：补丁是照着某一版上游写的，上游一改就可能静默失效。
静默失效会产出一个「看起来正常、实际功能还在」的包 —— 比构建失败难查得多。
断言把静默失效变成红色 X。

**前端为什么不改构建产物**：`ui/islands/ui.js` 是 esbuild 压缩的单行产物，变量名
每次构建都整体重排。实测 v3.4.1→v3.4.2，基于产物的探针**全部失效**（只有不参与混淆的
字符串字面量还命中）。所以前端补丁改 `.tsx` / `.ts` 源码，构建在补丁之后跑。

---

## 本地跑一遍

前置：

- Rust（`rustup`，需要 `aarch64-linux-android` target）
- Android NDK **r27d**（`ANDROID_NDK_HOME` 指过去）
- Node 22（前端构建）
- Python 3.9+（脚本与测试）

```bash
# 0. 补丁引擎自测（秒级，不需要上游源码）
python3 tests/test_patches.py

# 1. 拉两套源码
git clone --depth 1 --branch v3.4.2 https://github.com/aimod-cc/Agent2API build/up
git clone --depth 1 --branch v3.4.2 https://github.com/ProvidersPlugin/Agent2Providers build/px

# 2. 打补丁（顺序：先 rust 再 frontend 无所谓，两者改的是不同文件）
python3 patches/apply.py build/up --only rust
python3 patches/apply.py build/up --only frontend

# 3. 构建前端（必须在编译 Rust 之前 —— ui.js 被 include_str! 编进二进制）
cd build/up/desktop-tauri/ui-islands && npm ci && npm run typecheck && npm run build
cd ../ui-kit && npm ci          # ui-islands 的 @ui 指向这里，不装 typecheck 会喷 TS2307
cd ../ui-islands && npm run typecheck

# 4. 交叉编译
export ANDROID_NDK_HOME=/path/to/android-ndk-r27d
bash scripts/build.sh server    build/up/desktop-tauri/src-tauri out/agent2api-server
bash scripts/build.sh providers build/px                            out/agent2api-providers

# 5. 生成清单 + 打包 + 自检
python3 scripts/prepare.py --version v3.4.2 --plugin-version 3.4.2 \
    --server-bin out/agent2api-server --providers-bin out/agent2api-providers \
    --ui-ui build/up/desktop-tauri/ui --plugin-src build/px
python3 scripts/pack.py --out out/agent2api-magisk-v3.4.2.zip
python3 scripts/verify.py --zip out/agent2api-magisk-v3.4.2.zip \
    --version v3.4.2 --plugin-version 3.4.2 \
    --source build/up/desktop-tauri/src-tauri/server/src
```

**重跑补丁前先回滚**：`cd build/up && git checkout -- .`
（补丁会删文件，零幂等；不先回滚会报「要删的文件不存在」）

### Windows / msys 上的两个坑

`build.sh` 已经处理了，但值得知道：

1. `clang.exe` / `llvm-ar.exe` 是**原生 Windows 程序**，不认 msys 的 `/tmp`。`TMP` 必须
   `cygpath -w` 成 `C:\...`，而且目录要真实存在。
2. `CARGO_TARGET_DIR` **不能带空格**。`ring` 的 `.S` 汇编在带空格的路径下会失败（
   `process didn't exit successfully ... exit code: 1`，且没有 stderr）。

---

## 装机

```bash
# 手机开着无线调试（或 USB），Magisk 已 root
adb push agent2api-magisk-v3.4.2.zip /data/local/tmp/a2a.zip
adb shell su -c "magisk --install-module /data/local/tmp/a2a.zip"
adb reboot
```

Magisk 的机制是：`--install-module` 把内容写进 `/data/adb/modules_update/<id>` 并在
`/data/adb/modules/<id>/update` 留个标记，**重启后**才合并过去。所以刷完必须重启。

装好后：

| 项 | 值 |
|---|---|
| 面板 | `http://127.0.0.1:3065/`（手机浏览器），局域网 `http://<手机IP>:3065/` |
| 数据目录 | `/data/adb/agent2api/` |
| 配置 | `/data/adb/agent2api/module.conf`（首次开机自动生成） |
| 日志 | `/data/adb/agent2api/logs/` |
| 控制 | `su -c "sh /data/adb/modules/agent2api/ctl.sh status"` |

`ctl.sh` 的子命令：`start` / `stop` / `restart` / `status` / `plugins` / `logs`。
Magisk 应用里点模块的「操作」按钮跑的也是它（`action.sh`）。

### 首次启动会发生什么

1. `service.sh` 等 `sys.boot_completed`（最多 120 秒）；
2. 首次生成 `module.conf`（`HOST=127.0.0.1`、`PORT=3065`、`CAPTCHA=1`、`ALLOW_NO_KEY=0` …）；
3. `plugin-setup.sh` 把 `plugin-pack/` 铺到 `/data/adb/agent2api/plugins/agent2api-providers/<版本>/`
   并在 `plugins.json` 里登记（升级路径见下）；
4. `setsid` 起 `watchdog.sh`，由它看住网关进程。

面板第一次打开会让你注册管理员账号。

### 插件升级路径（v3.4.1 修过的一个坑）

`plugin-setup.sh` 判定逻辑是三分支，比较的是**注册表里已装的版本**与**模块自带的版本**：

| 注册表版本 | 动作 |
|---|---|
| 比模块自带**高** | 跳过，不降级（用户在面板里装过更新的） |
| **相同** | 只补缺失文件，注册表字节不动 |
| 比模块自带**低** | 铺新版本目录 → 整条替换注册表条目 → 清旧版本目录 |

比较用 `ver_gt()` 逐段比数值，**不用 `sort -V`**（Android 的 toybox 不保证支持）。
整条替换而不是只改 `version` 字段：`providers` 布尔表与 `manifest_providers` 也要换成新的，
否则新提供商在 `pack.json` 读不到清单时会回落到旧集合。

---

## 每天跟上游

`.github/workflows/daily-sync.yml`，`cron: "17 4 * * *"`（04:17 UTC / 12:17 北京）。

```
probe   ──► 查上游 + 插件仓库最新 tag，与 upstream.json 比
            有新版本 → changed=true
              │
              ▼
build   ──► 复用 build.yml 真跑一遍（约 20 分钟）
            成功 → 发 release + 写回 upstream.json
            失败 → 什么都不记（版本号留在旧值，明天再试）
              │
              ▼
alarm   ──► 上面失败了就开 issue，正文附「哪个补丁挂了」+ 上游 diff 链接
```

**为什么先真构建再记版本**：如果先写 `upstream.json` 再构建，一旦构建失败，第二天
probe 会认为「已经是最新」，从此再也不重试 —— 一个坏版本会永久卡住同步。所以
版本号只在**构建成功之后**才写。

**issue 里会带什么**：`patches/apply.py` 在临时 clone 的上游上重跑一遍，从输出里 grep
`✗` 那一行，拿到失败补丁的文件名与断言消息。同日重复失败不会刷屏（按标题判重，往原
issue 追加 comment）。

---

## 验证做到了什么程度

`scripts/verify.py` 对**产出的 zip** 做 9 组检查，任何一组失败就不发 release：

1. 22 个必备文件齐全（两个二进制、`ui/`、`plugin-pack/`、`plugin-registry/`、脚本、`META-INF`）
2. `module.prop` 的 `version` / `versionCode` / `id` 正确，中文没有替换字符
3. 四处版本一致（`module.prop`、`pack.json`、`plugins.json`、`registry-entry.json`）；
   `pack.json` 的 `entry` 只剩 `aarch64-unknown-linux-gnu` 一条；注册表的 provider 布尔表
   与 `manifest_providers` 与 `pack.json` **逐项相等**
4. 两个二进制是 aarch64 ELF（`e_machine == 0xB7`）且内嵌了正确的插件版本串
5. `ui/` 至少 200 个文件；4 个 JS 过 `node --check`；`app.js` / `sidebar-layout.js` /
   `ui.js` 里 16 个「已裁功能」的标记**一个都不许出现**（`publishUpdateStatus`、
   `nav-count-update`、`本机接入`、`/api/agents`、`wbAgentPanel` …），
   同时 `install-info`（保留的端点）**必须还在**
6. 扫后端 `.rs` 里的路由字面量，已裁的 12 条路由一条都不许残留
7. 8 个 shell 脚本过 `sh -n`
8. 5 个 JSON 严格解析
9. zip 的 CRC 全部通过；10 个可执行项权限必须是 `0755`（缺了 `update-binary` 就跑不起来）

除了 `verify.py`，仓库里还有两层：

- `tests/test_patches.py` —— 补丁引擎自身的语义测试（计数、行尾归一、`tail` 边界、
  `versionCode` 映射单调性、补丁清单完整性）
- 每次构建都会跑 `patches/apply.py` 的全部断言 —— 上游一改，构建在打补丁那一步就红，
  不会产出错版包

---

## 常见问题

**构建卡在 `cargo` 拉 git 依赖**
上游 `server/Cargo.toml` 把 `agent2api-provider-protocol` 钉在一个 git tag 上。本机
`~/.cargo/git/db/` 里如果是空壳会卡十分钟。绕法：在 `src-tauri/.cargo/config.toml` 加

```toml
[patch."https://github.com/ProvidersPlugin/Agent2Providers"]
agent2api-provider-protocol = { path = "…/build/px/crates/provider-protocol" }
```

CI 上不需要（网络正常）。**这个 patch 不要提交**，它是本地环境问题的绕法。

**插件装上了但面板里没新增提供商**
看 `logs/` 里的 `已加载，N 家提供商可用`。N 会比 `pack.json` 的提供商总数少：
`demo` 默认停用（`default_enabled: false`），另有几个被上游 `SUSPENDED_IDS` 过滤
（国际站等只在特定地区可用）。这是上游行为。

**面板打不开，但进程在**
`ctl.sh status` 看监听端口与健康检查。端口被占时 `service.sh` 会等，日志里有记录。
默认只监听 `127.0.0.1`；要局域网访问，改 `module.conf` 的 `HOST=0.0.0.0` 并重启。

---

## 许可

模块骨架与补丁脚本：AGPL-3.0（与上游一致）。
`module/LICENSE` 是上游的许可证原件。
