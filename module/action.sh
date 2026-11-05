#!/system/bin/sh
# 模块「操作」按钮（KernelSU / APatch 的模块卡片上那个按钮，Magisk 部分管理器也支持）
#
# 点了之后做一次「状态巡检」，把结果打到管理器界面上。没有交互能力，
# 所以只报告不改状态——改状态用 ctl.sh。

MODDIR=${0%/*}
DATA_DIR=/data/adb/agent2api
PID_FILE="$DATA_DIR/gateway.pid"
CONF="$DATA_DIR/module.conf"

. "$CONF" 2>/dev/null
: "${HOST:=127.0.0.1}"
: "${PORT:=3065}"

gw_pids() {
  ps -A -o PID,NAME 2>/dev/null \
    | grep agent2api-server \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# 端口探活。Android 的 sh 是 mksh，**没有 /dev/tcp**（那是 bash 特性），
# 所以只能看 netstat。
probe_tcp() {
  if netstat -tln 2>/dev/null | tr -d '\r' | grep 'LISTEN' | grep -q ":$1 "; then
    echo 200
  else
    echo 000
  fi
}

echo "Agent2API 网关"
echo "----------------------"

pid=$(gw_pids | head -n 1)
if [ -n "$pid" ]; then
  echo "进程: 运行中 (pid $pid)"
else
  echo "进程: 未运行"
fi

if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null)
else
  code=$(probe_tcp "$PORT")
fi

if [ -n "$code" ] && [ "$code" != "000" ]; then
  echo "健康: HTTP $code"
else
  echo "健康: 不通"
fi

echo "监听: $HOST:$PORT"
echo "面板: http://127.0.0.1:$PORT/"

# 局域网地址（HOST=0.0.0.0 时把本机 IP 也打出来，方便别的设备直接复制）
if [ "$HOST" = "0.0.0.0" ]; then
  ip=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -n 1)
  if [ -z "$ip" ]; then
    ip=$(ip -4 addr show wlan0 2>/dev/null | sed -n 's/.*inet \([0-9.]*\).*/\1/p' | head -n 1)
  fi
  [ -n "$ip" ] && echo "局域网: http://$ip:$PORT/"
fi

echo "----------------------"
echo "启动/停止/重启:"
echo "  su -c 'sh /data/adb/modules/agent2api/ctl.sh start|stop|restart'"
echo "局域网开关:"
echo "  su -c 'sh /data/adb/modules/agent2api/ctl.sh lan on|off'"
