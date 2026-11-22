#!/system/bin/sh
# Magisk / KernelSU / APatch 安装脚本
#
# 被模块安装器 source 执行，可用变量：
#   $MODPATH  模块的临时解包目录
#   $ARCH     arm64 / arm / x86_64 / x86 / riscv64
#   $API      设备的 Android API 级别
#   ui_print  打印一行到安装日志
#
# 注意：本文件被 **source** 执行，所以不要 exit，要中止用 abort。

SKIPUNZIP=0

# 安装器（Magisk / KernelSU / APatch）会注入 ui_print / abort / set_perm 等函数。
# 但「手工解包再跑一遍」或某些分支的精简安装器不会注入 —— 那时脚本会一路
# 报 `ui_print: inaccessible or not found` 并带着 127 退出，看着像安装失败。
# 给个退路，让脚本在任何宿主下都能跑完。
if ! command -v ui_print >/dev/null 2>&1; then
  ui_print() { echo "$@"; }
fi
if ! command -v abort >/dev/null 2>&1; then
  abort() { echo "$@"; exit 1; }
fi

ui_print "- Agent2API 网关 Magisk 模块"

# ── 架构检查 ────────────────────────────────────────────────
# 只编了 arm64（aarch64）的二进制：手机基本全是 arm64，其它架构直接拦下，
# 免得装上一个跑不起来的模块占着位置。
case "$ARCH" in
  arm64|arm64-v8a) ;;
  *)
    ui_print "! 本模块仅提供 arm64-v8a 二进制，当前设备架构：$ARCH"
    ui_print "! 32 位机型请自行交叉编译后放入 bin/ 目录"
    abort "! 架构不支持"
    ;;
esac

# ── Android 版本 ────────────────────────────────────────────
# 二进制按 API 26（Android 8.0）链接；更老的系统缺符号，直接拦。
if [ -n "$API" ] && [ "$API" -lt 26 ]; then
  ui_print "! 需要 Android 8.0 (API 26) 及以上，当前 API $API"
  abort "! 系统版本过低"
fi

# ── 解包兜底 ────────────────────────────────────────────────
# 正常情况下安装器已经解包了（SKIPUNZIP=0）。但部分 Magisk 分支 / 手工安装
# 场景下不会自动解包，这里检测一下，缺文件就自己解，避免装出个空模块。
if [ ! -f "$MODPATH/bin/agent2api-server" ] && [ -n "$ZIPFILE" ] && [ -f "$ZIPFILE" ]; then
  ui_print "- 检测到未解包，手动解压"
  unzip -o -q "$ZIPFILE" -d "$MODPATH" 2>/dev/null
fi

if [ ! -f "$MODPATH/bin/agent2api-server" ]; then
  ui_print "! 模块缺少 bin/agent2api-server"
  abort "! 安装包不完整"
fi

# ── 铺设权限 ────────────────────────────────────────────────
ui_print "- 设置权限"

# Magisk / KernelSU 安装器会注入 set_perm_recursive，走它最快。
if command -v set_perm_recursive >/dev/null 2>&1; then
  set_perm_recursive "$MODPATH" 0 0 0755 0644
else
  # 手工/精简安装器没有 set_perm_recursive。
  # 注意必须用 `-exec ... {} +`（批量）而不是 `{} \;`（每文件 fork 一次）：
  # zip 里有 280+ 个文件，逐个 fork chmod 在 OPPO R11 这种老机器上要跑几分钟，
  # 安装器早超时了。批量形式只调用 chmod 几十次。
  find "$MODPATH" -type d -exec chmod 0755 {} + 2>/dev/null
  find "$MODPATH" -type f -exec chmod 0644 {} + 2>/dev/null
fi

# 可执行文件：二进制 + 所有脚本（逐个来，不依赖 set_perm 是否存在）
for f in \
  "$MODPATH/bin/agent2api-server" \
  "$MODPATH/plugin-pack/bin/agent2api-providers" \
  "$MODPATH/service.sh" \
  "$MODPATH/watchdog.sh" \
  "$MODPATH/plugin-setup.sh" \
  "$MODPATH/ctl.sh" \
  "$MODPATH/uninstall.sh" \
  "$MODPATH/action.sh" \
  "$MODPATH/customize.sh" \
  "$MODPATH/META-INF/com/google/android/update-binary"
do
  [ -f "$f" ] || continue
  if command -v set_perm >/dev/null 2>&1; then
    set_perm "$f" 0 0 0755
  fi
  chmod 0755 "$f" 2>/dev/null
done

# ui/ 面板静态资源：目录 755、文件 644（纯读取，不需要可执行）
if [ -d "$MODPATH/ui" ]; then
  find "$MODPATH/ui" -type d -exec chmod 0755 {} + 2>/dev/null
  find "$MODPATH/ui" -type f -exec chmod 0644 {} + 2>/dev/null
fi

# plugin-pack/：插件二进制 755，其余（pack.json / assets / ui）644
if [ -d "$MODPATH/plugin-pack" ]; then
  find "$MODPATH/plugin-pack" -type d -exec chmod 0755 {} + 2>/dev/null
  find "$MODPATH/plugin-pack" -type f -exec chmod 0644 {} + 2>/dev/null
  chmod 0755 "$MODPATH/plugin-pack/bin/agent2api-providers" 2>/dev/null
fi

# ── 自检 ────────────────────────────────────────────────────
if [ ! -x "$MODPATH/bin/agent2api-server" ]; then
  chmod 0755 "$MODPATH/bin/agent2api-server" 2>/dev/null
fi
if [ ! -x "$MODPATH/bin/agent2api-server" ]; then
  ui_print "! 无法为二进制设置可执行位"
  abort "! 安装失败"
fi

ui_print "- 数据目录 /data/adb/agent2api（首次启动自动创建）"
if [ -f "$MODPATH/plugin-pack/bin/agent2api-providers" ]; then
  ui_print "- 已内置提供商插件 v3.5.0-beta.3（首次启动自动铺设，34 家实现）"
else
  ui_print "! 未内置提供商插件：v3.4.0 起账号页会显示为空"
fi
ui_print "- 面板 http://127.0.0.1:3065/"
ui_print "- 重启后自动在后台运行；也可执行:"
ui_print "    su -c 'sh /data/adb/modules/agent2api/ctl.sh start'"
