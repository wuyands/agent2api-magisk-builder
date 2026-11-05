#!/system/bin/sh
# Agent2API 网关守护循环（watchdog）
#
# 独立成一个脚本，而不是塞在 service.sh 里的 subshell —— 因为要按命令行
# 认出「谁是守护进程」，subshell 的 cmdline 跟父脚本一模一样，ps 分不出来。
# 独立脚本的 cmdline 是 `sh /data/adb/modules/agent2api/watchdog.sh`，
# 全局唯一，`wd_pids()` 可以准确匹配。
#
# 生命周期由 ctl.sh 管：
#   start/restart → 先用最新配置重建 watcher（环境变量只在启动时读一次，
#                   所以改完 module.conf 必须重启 watcher，否则它拉起的
#                   网关还是旧 HOST）
#   stop          → 先停 watcher 再停网关（反过来会被 watcher 立刻拉回来）
#
# 直接手动跑也可以：sh watchdog.sh &

MODDIR=${0%/*}
DATA_DIR=/data/adb/agent2api
CONF="$DATA_DIR/module.conf"
LOG_DIR="$DATA_DIR/logs"
PID_FILE="$DATA_DIR/gateway.pid"
BIN="$MODDIR/bin/agent2api-server"

mkdir -p "$LOG_DIR"

# ── 读配置（只读一次，写进本进程环境）───────────────────────
if [ -f "$CONF" ]; then
  . "$CONF"
fi
: "${HOST:=127.0.0.1}"
: "${PORT:=3065}"
: "${CAPTCHA:=1}"
: "${ALLOW_NO_KEY:=0}"
: "${IMAGE_CACHE_MB:=32}"
: "${IMAGE_COMPRESS_CACHE_MB:=32}"

export AGENT2API_PROXY_HOME="$DATA_DIR"
export AGENT2API_HOST="$HOST"
export AGENT2API_PROXY_PORT="$PORT"
export AGENT2API_UI_DIR="$MODDIR/ui"
export AGENT2API_CAPTCHA_ENABLED="$CAPTCHA"
export HOME="$DATA_DIR"
export TMPDIR="$DATA_DIR/tmp"
mkdir -p "$TMPDIR"

[ -n "$ADMIN_USER" ] && export AGENT2API_ADMIN_USER="$ADMIN_USER"
[ -n "$ADMIN_PASSWORD" ] && export AGENT2API_ADMIN_PASSWORD="$ADMIN_PASSWORD"
[ "$ALLOW_NO_KEY" = "1" ] && export AGENT2API_ALLOW_NO_KEY=1
[ -n "${IMAGE_CACHE_MB:-}" ] && export AGENT2API_IMAGE_CACHE_MB="$IMAGE_CACHE_MB"
[ -n "${IMAGE_COMPRESS_CACHE_MB:-}" ] && export AGENT2API_IMAGE_COMPRESS_CACHE_MB="$IMAGE_COMPRESS_CACHE_MB"
[ -n "${EXTRA_ENV:-}" ] && export $EXTRA_ENV

[ -f "$BIN" ] || exit 0
chmod 755 "$BIN" 2>/dev/null

# ── 提供商插件铺设（幂等）─────────────────────────────────
# 放在这里而不是只在 service.sh 里，是因为 watchdog 是所有启动路径
# 的唯一入口（开机、ctl.sh start、崩溃后自动恢复）。
# 只在 service.sh 里铺的话，`ctl.sh start` 或数据目录被清过之后
# 网关会在「没有插件」的状态下起来 —— 账号页空白、/v1 报 503。
# plugin-setup.sh 自身幂等且不降级，重复调用无副作用。
PS="$MODDIR/plugin-setup.sh"
if [ -f "$PS" ]; then
  chmod 755 "$PS" 2>/dev/null
  sh "$PS"
fi

# ── 进程识别（按进程名，不信 pid 文件）─────────────────────
gw_pids() {
  ps -A -o PID,NAME 2>/dev/null \
    | grep agent2api-server \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

running() {
  [ -n "$(gw_pids)" ]
}

start_gateway() {
  cd "$DATA_DIR" || return 1
  if command -v setsid >/dev/null 2>&1; then
    setsid "$BIN" >> "$LOG_DIR/gateway.log" 2>&1 &
  else
    "$BIN" >> "$LOG_DIR/gateway.log" 2>&1 &
  fi
}

# 日志轮转：超过 2MB 就滚一份，避免长期运行把日志写爆
rotate_log() {
  size=$(wc -c < "$LOG_DIR/gateway.log" 2>/dev/null || echo 0)
  if [ "${size:-0}" -gt 2097152 ]; then
    mv -f "$LOG_DIR/gateway.log" "$LOG_DIR/gateway.log.1"
  fi
}

echo "[watchdog] 启动 (pid $$, HOST=$HOST PORT=$PORT)" >> "$LOG_DIR/watcher.log"

backoff=5
while true; do
  if ! running; then
    rotate_log
    start_gateway
    # 轮询等它出现，而不是固定 sleep 3 ——
    # 网关要初始化十几个 provider，冷启动经常超过 3 秒，
    # 固定等待会把「还在启动」误判成「启动失败」，
    # 于是 watcher 进退避、放弃拉起，服务看起来就"没有守护"了。
    waited=0
    while [ "$waited" -lt 15 ]; do
      sleep 1
      waited=$((waited + 1))
      running && break
    done
    if running; then
      backoff=5
      # 真实 pid 回写，供 ctl.sh status 显示
      gw_pids | head -n 1 > "$PID_FILE"
    else
      # 连续起不来就拉长重试间隔，最多 5 分钟
      backoff=$((backoff * 2))
      [ "$backoff" -gt 300 ] && backoff=300
      echo "[watchdog] 启动失败（等待 ${waited}s 后仍无进程），${backoff}s 后重试" >> "$LOG_DIR/watcher.log"
      sleep "$backoff"
      continue
    fi
  fi
  sleep 30
done
