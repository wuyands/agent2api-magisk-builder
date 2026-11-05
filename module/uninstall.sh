#!/system/bin/sh
# 模块卸载时执行（Magisk 在删除模块目录前调用）
#
# 策略：**只停进程，不删数据**。
# /data/adb/agent2api 里有账号凭证、网关 Key、请求报表，属于用户资产；
# 卸载模块多半只是想换个版本或先关掉。真要把数据一起清掉，卸载后手动：
#   rm -rf /data/adb/agent2api

DATA_DIR=/data/adb/agent2api
PID_FILE="$DATA_DIR/gateway.pid"
WD_PID_FILE="$DATA_DIR/watchdog.pid"

# 按进程名找真实 pid（不信 pid 文件 —— 守护循环可能已换过实例）
gw_pids() {
  ps -A -o PID,NAME 2>/dev/null \
    | grep agent2api-server \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

wd_pids() {
  ps -A -o PID,ARGS 2>/dev/null \
    | grep "agent2api/watchdog.sh" \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# 插件宿主进程（v3.4.0 起网关会派生一个 agent2api-providers 子进程）。
# 正常情况下网关退出它就跟着走，但被 kill -9 时可能留下孤儿，
# 它握着宿主通道的 socket，重新装模块时会报端口/握手错误。
px_pids() {
  ps -A -o PID,NAME 2>/dev/null \
    | grep agent2api-providers \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# ── 顺序：先 watchdog，后网关 ───────────────────────────────
# 反过来做的话，watchdog 会在 30 秒内把网关重新拉起来，
# 卸载完看起来「服务还在跑」，而模块目录已经没了。
wd=$(wd_pids)
if [ -n "$wd" ]; then
  for p in $wd; do
    kill "$p" 2>/dev/null
  done
  i=0
  while [ -n "$(wd_pids)" ] && [ "$i" -lt 5 ]; do
    sleep 1
    i=$((i + 1))
  done
  for p in $(wd_pids); do
    kill -9 "$p" 2>/dev/null
  done
fi

pids=$(gw_pids)
if [ -n "$pids" ]; then
  for p in $pids; do
    kill "$p" 2>/dev/null
  done
  i=0
  while [ -n "$(gw_pids)" ] && [ "$i" -lt 5 ]; do
    sleep 1
    i=$((i + 1))
  done
  for p in $(gw_pids); do
    kill -9 "$p" 2>/dev/null
  done
fi

rm -f "$PID_FILE" "$WD_PID_FILE"

# 插件宿主孤儿清理（网关被杀后它可能还挂着）
px=$(px_pids)
if [ -n "$px" ]; then
  for p in $px; do
    kill "$p" 2>/dev/null
  done
  sleep 1
  for p in $(px_pids); do
    kill -9 "$p" 2>/dev/null
  done
fi

exit 0
