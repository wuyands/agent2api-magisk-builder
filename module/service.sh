#!/system/bin/sh
# Agent2API 网关 —— 开机自启入口（Magisk late_start service 阶段）
#
# 职责很窄：
#   1. 等系统真的起来（boot_completed），否则网络栈与 /data 可能还没就绪；
#   2. 准备好数据目录与配置（首次运行生成 module.conf）；
#   3. 铺好提供商插件（plugin-setup.sh，v3.4.0 起必需）；
#   4. 确认守护循环 watchdog.sh 在跑 —— 网关由它拉起和保活。
#
# 拉起逻辑只有一份，在 watchdog.sh 里。本脚本不直接起网关，
# 避免「ctl.sh 起一个 + watcher 起一个」抢同一个端口。
#
# 注意：本脚本由 Magisk 以 root 在 late_start 阶段执行，**必须很快返回**
# —— 长时间阻塞会拖慢开机。所以 watchdog 是 setsid 到后台的独立进程。
#
# 也可以由 ctl.sh 手动调用（`ctl.sh watchdog`）。

MODDIR=${0%/*}
DATA_DIR=/data/adb/agent2api
CONF="$DATA_DIR/module.conf"
LOG_DIR="$DATA_DIR/logs"
WD_PID_FILE="$DATA_DIR/watchdog.pid"
WD="$MODDIR/watchdog.sh"

# ── 1. 等开机完成 ────────────────────────────────────────────
# sys.boot_completed 变 1 之前网络栈可能还没准备好（有些设备 service 阶段
# 比 ConnectivityService 早）。最多等 120 秒，超时也继续（不能永远不启动）。
# 已经 boot_completed 的话这里立即通过，不会拖慢 ctl.sh 的调用。
i=0
while [ "$(getprop sys.boot_completed)" != "1" ]; do
  i=$((i + 1))
  [ "$i" -gt 120 ] && break
  sleep 1
done

mkdir -p "$DATA_DIR" "$LOG_DIR"

# ── 2. 首次运行生成配置 ──────────────────────────────────────
if [ ! -f "$CONF" ]; then
  cat > "$CONF" <<'EOC'
# Agent2API 网关模块配置（改完执行 `sh /data/adb/agent2api/ctl.sh restart` 生效）
#
# 监听地址：127.0.0.1 = 只有手机本机能访问（最安全，默认）
#           0.0.0.0  = 同一局域网内的电脑/平板也能访问（面板会暴露在局域网，
#                      首次打开必须先注册管理员，注册完成前任何能连上的人都能抢注）
# 快捷切换：sh /data/adb/agent2api/ctl.sh lan on|off
HOST=127.0.0.1
# 监听端口
PORT=3065
#
# 面板管理员（可选）：留空则在网页上首次注册；
# 填了就跳过注册窗口期，直接按这组账号登录。
# 密码明文写在这里会在启动时自动转成 bcrypt 哈希存库，配置文件本身不做保护
# —— 手机是私人物品，这个取舍与 Docker 版一致。
ADMIN_USER=
ADMIN_PASSWORD=
#
# 内置人机验证（登录页）：1 开启（默认），0 关闭
# 注意：关掉之后 /api/panel/setup 就可以被脚本直接调用注册管理员
CAPTCHA=1
#
# 不配任何 API Key 时是否放行 /v1/* 请求
#   0 = 拒绝（默认，安全）：先去面板「网关 Key」页建一把
#   1 = 全部放行：纯本机自用懒得配 Key 时用，**不要**在 HOST=0.0.0.0 下开
ALLOW_NO_KEY=0
#
# ── 图片缓存（v3.4.0 新增）────────────────────────────────
# 网关会把生图结果和「会话图片压缩」的产物缓存在内存里。
# 上游默认各 128MB（合计 256MB），那是按桌面/服务器定的；
# 手机内存紧张，这里给 32MB / 32MB —— 缓存只是加速，调小不影响功能。
# 范围 8~4096，写坏了会回落默认值、不会报错。
IMAGE_CACHE_MB=32
IMAGE_COMPRESS_CACHE_MB=32
#
# 只监听本机时通常够用；需要调 DNS/超时之类再往下加 export
# EXTRA_ENV="AGENT2API_VERBOSE=1"
EOC
  chmod 600 "$CONF"
fi

# ── 3. 提供商插件 ────────────────────────────────────────────
# v3.4.0 起 provider 实现全在独立进程插件包里，没有插件时
# `is_executable_provider()` 恒为 false → 账号页把账号全判 not_installed
# 隐藏、/v1 直接 503。所以模块自带 plugin-pack/，这里铺好再起网关。
# 脚本本身幂等：已在位就不动，已登记就不改注册表。
PS="$MODDIR/plugin-setup.sh"
if [ -f "$PS" ]; then
  chmod 755 "$PS" 2>/dev/null
  sh "$PS"
fi

# ── 4. 守护循环 ──────────────────────────────────────────────
[ -f "$WD" ] || exit 0
[ -f "$MODDIR/bin/agent2api-server" ] || exit 0
chmod 755 "$MODDIR/bin/agent2api-server" "$WD" 2>/dev/null

# 用「命令行里带 agent2api/watchdog.sh」识别已有实例。
# watchdog.sh 是独立脚本，cmdline 全局唯一，不像 subshell 那样
# 跟父进程同名 —— 这是把守护循环拆出去的原因。
wd_pids() {
  ps -A -o PID,ARGS 2>/dev/null \
    | grep "agent2api/watchdog.sh" \
    | grep -v grep \
    | sed 's/^ *//' | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# 已有守护循环就不再起第二个（两个 watchdog 会抢同一个端口）
existing=$(wd_pids)
if [ -n "$existing" ]; then
  echo "$existing" | head -n 1 > "$WD_PID_FILE"
  exit 0
fi

if command -v setsid >/dev/null 2>&1; then
  setsid sh "$WD" >/dev/null 2>&1 &
else
  sh "$WD" >/dev/null 2>&1 &
fi

# watchdog.sh 自己会把 pid 写进 CONFIG 同级的 watchdog.pid；
# 这里等一小会儿，让它在 Magisk 收集脚本状态之前就位。
i=0
while [ "$i" -lt 3 ]; do
  sleep 1
  p=$(wd_pids | head -n 1)
  if [ -n "$p" ]; then
    echo "$p" > "$WD_PID_FILE"
    break
  fi
  i=$((i + 1))
done

exit 0
