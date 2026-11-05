#!/system/bin/sh
# Agent2API 模块命令行控制
#
# 用法：
#   sh /data/adb/agent2api/ctl.sh start|stop|restart|status|log|config|port
#   sh /data/adb/agent2api/ctl.sh lan on|off      （开放/关闭局域网访问）
#
# 也可以从任意 root shell 直接调用，不需要进模块目录。
#
# ── 设计要点：为什么 start/stop 要管「守护循环」──────────────
# 守护循环（watchdog）是一个长期存活的后台 shell，它在启动那一刻
# 就把 HOST/PORT 等环境变量读进了自己的进程环境。之后无论 module.conf
# 怎么改，它拉起来的网关都还是**旧配置**。
#
# 后果：ctl.sh restart 杀掉网关后，watchdog 立刻用旧环境拉起新实例
# → 新配置不生效 → 用户看到「改了配置没反应」或「端口被占用」。
#
# 所以这里把 watchdog 也纳入生命周期：
#   start  → 先停旧 watchdog，再起新的（读到最新配置）
#   stop   → 连 watchdog 一起停，否则它马上把网关拉回来
# pid 存在 $RUN_DIR/watchdog.pid。

MODDIR=${0%/*}
DATA_DIR=/data/adb/agent2api
CONF="$DATA_DIR/module.conf"
LOG_DIR="$DATA_DIR/logs"
PID_FILE="$DATA_DIR/gateway.pid"
WD_PID_FILE="$DATA_DIR/watchdog.pid"
BIN="$MODDIR/bin/agent2api-server"

# ── 进程识别 ────────────────────────────────────────────────
# 关键：**不能只信 pid 文件**。
#   1. 守护循环会在进程崩溃后拉起新的实例，新旧 pid 交替时 pid 文件很容易过期；
#   2. setsid 场景下 `$!` 拿到的是 setsid 自己的 pid，
#      而真正 bind 端口的可能是它 exec 出来的子进程。
# 所以统一按「进程名」找真实 pid，pid 文件只用来加速和显示。
gw_pids() {
  ps -A -o PID,NAME 2>/dev/null \
    | grep agent2api-server \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# 守护循环的 pid：优先 pid 文件（校验它真的是那个脚本），否则按命令行找。
# watchdog.sh 是独立脚本，cmdline 唯一，ps 能准确区分
# （以前把守护循环写成 service.sh 里的 subshell，cmdline 与父进程同字，
#  匹配出来的是调用者自己，导致「以为已有 watcher」而不起 —— 已修）。
wd_pids() {
  if [ -f "$WD_PID_FILE" ]; then
    p=$(cat "$WD_PID_FILE" 2>/dev/null)
    case "$p" in
      ''|*[!0-9]*) ;;
      *)
        if ps -A -o PID,ARGS 2>/dev/null | grep -v grep | grep "agent2api/watchdog.sh" | sed 's/^ *//' | sed 's/ .*//' | grep -qx "$p"; then
          echo "$p"
          return 0
        fi
        ;;
    esac
  fi
  ps -A -o PID,ARGS 2>/dev/null \
    | grep "agent2api/watchdog.sh" \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# 主 pid：优先 pid 文件（且必须真的是网关进程），否则取第一个真实进程
gw_pid() {
  if [ -f "$PID_FILE" ]; then
    p=$(cat "$PID_FILE" 2>/dev/null)
    case "$p" in
      ''|*[!0-9]*) ;;
      *)
        if gw_pids | grep -qx "$p"; then
          echo "$p"
          return 0
        fi
        ;;
    esac
  fi
  gw_pids | head -n 1
}

running() {
  [ -n "$(gw_pids)" ]
}

# 已铺设的插件入口二进制（取第一个匹配；版本目录由 plugin-setup.sh 决定，
# 模块升级后目录名会跟着变，所以这里不能写死版本号）。
px_bin() {
  for f in "$DATA_DIR"/plugins/agent2api-providers/*/bin/agent2api-providers; do
    [ -f "$f" ] && { printf '%s
' "$f"; return 0; }
  done
  return 0
}

# 插件宿主进程（v3.4.0 起网关派生的 agent2api-providers）。
# 网关正常退出它跟着走；被 kill -9 时会留孤儿，握着宿主 socket，
# 下次启动可能报握手/端口错误 —— 所以停网关时顺手清掉。
px_pids() {
  ps -A -o PID,NAME 2>/dev/null \
    | grep agent2api-providers \
    | grep -v grep \
    | sed 's/^ *//' \
    | sed 's/ .*//' \
    | grep '^[0-9][0-9]*$'
}

# 端口是否有进程在 LISTEN。
#
# ⚠️ 这里**不能用 /dev/tcp**：那是 bash 的特性，Android 的 /system/bin/sh
# 是 mksh，`exec 3<>/dev/tcp/127.0.0.1/3065` 只会报
# `can't create /dev/tcp/...: No such file or directory` 并返回非 0。
# 用它的后果不是"探测失败"，而是"永远判定端口空闲"——
# do_start 的 `running && port_busy` 于是永远为假，网关明明起来了，
# 脚本等满 20 秒后打印"启动失败"。改用 netstat。
port_busy() {
  p="$1"
  netstat -tln 2>/dev/null \
    | tr -d '\r' \
    | grep 'LISTEN' \
    | grep -q ":$p "
}

# 探活（curl 不可用时的退路）：能看到 LISTEN 就算通。
# 它不是真正的 HTTP 检查，只回答"端口上有没有人在听"。
probe_tcp() {
  if port_busy "$1"; then
    echo 200
  else
    echo 000
  fi
}

load_conf() {
  [ -f "$CONF" ] && . "$CONF"
  : "${HOST:=127.0.0.1}"
  : "${PORT:=3065}"
  : "${CAPTCHA:=1}"
  : "${ALLOW_NO_KEY:=0}"
  : "${IMAGE_CACHE_MB:=32}"
  : "${IMAGE_COMPRESS_CACHE_MB:=32}"
}

# ── 停止 ────────────────────────────────────────────────────
# 顺序很重要：**先停守护循环，再停网关**。
# 反过来做的话，watchdog 会在网关消失的 30 秒内立刻把它拉回来。
stop_watchdog() {
  pids=$(wd_pids)
  [ -z "$pids" ] && return 0
  echo "正在停止守护循环 (pid $(echo $pids))..."
  for p in $pids; do
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
  rm -f "$WD_PID_FILE"
}

stop_gateway() {
  pids=$(gw_pids)
  if [ -z "$pids" ]; then
    rm -f "$PID_FILE"
    return 0
  fi
  echo "正在停止网关 (pid $(echo $pids))..."
  for p in $pids; do
    kill "$p" 2>/dev/null
  done
  i=0
  while [ -n "$(gw_pids)" ] && [ "$i" -lt 5 ]; do
    sleep 1
    i=$((i + 1))
  done
  for p in $(gw_pids); do
    echo "强制结束 pid $p"
    kill -9 "$p" 2>/dev/null
  done
  sleep 1
  rm -f "$PID_FILE"
}

do_stop() {
  stop_watchdog
  stop_gateway
  # 插件宿主孤儿（网关被 kill -9 时留下），不清掉会让下次启动握手失败
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
  echo "已停止"
}

# ── 启动 ────────────────────────────────────────────────────
# 拉起逻辑只有一份：watchdog.sh。这里不直接起网关，
# 否则会出现「ctl 起一个 + watchdog 起一个」抢同一端口的历史问题。
do_start() {
  load_conf
  if running; then
    echo "网关已在运行 (pid $(gw_pid))"
    do_watchdog
    return 0
  fi

  [ -f "$BIN" ] || { echo "错误：找不到 $BIN（模块未正确安装）"; return 1; }
  chmod 755 "$BIN" 2>/dev/null

  # 端口的残留占用：上一轮被 kill -9 时内核可能还没回收，或其它程序占着
  if port_busy "$PORT"; then
    echo "错误：端口 $PORT 已被占用，无法启动"
    echo "  查看占用者：netstat -tlnp | grep $PORT"
    return 1
  fi

  echo "=== 启动于 $(date '+%F %T') (HOST=$HOST PORT=$PORT) ===" >> "$LOG_DIR/gateway.log"

  # 守护循环按最新配置重建，并由它拉起网关
  stop_watchdog
  if ! do_watchdog; then
    echo "错误：守护循环启动失败（watchdog.sh 不存在或无法执行）"
    return 1
  fi

  # 等网关真正 bind 上端口，再回写真实 pid
  i=0
  while [ "$i" -lt 20 ]; do
    sleep 1
    if running && port_busy "$PORT"; then
      # 先把 pid 取到变量里再写文件。
      # `gw_pid > "$PID_FILE"` 这种写法会**先截断文件再求值**——
      # 重定向在任何命令执行前就生效，函数里读 pid 文件时它已经是空的了。
      # 平时靠后面的 gw_pids 兜底看不出来，但边界情况下会写进空值，
      # 于是 state 显示「已启动 (pid )」。
      p=$(gw_pid)
      [ -n "$p" ] && echo "$p" > "$PID_FILE"
      echo "已启动 (pid ${p:-未知})"
      echo "面板: http://$HOST:$PORT/"
      echo "接口: http://$HOST:$PORT/v1"
      return 0
    fi
    i=$((i + 1))
  done

  echo "启动失败，最近日志："
  tail -20 "$LOG_DIR/gateway.log"
  return 1
}

# 起守护循环：直接跑 watchdog.sh（它就是那个长期进程，
# cmdline 唯一，ps 能准确定位；不像 subshell 会跟父进程同名）。
# 环境变量由 watchdog.sh 自己从 module.conf 读取，所以这里不用先 export。
do_watchdog() {
  if [ -n "$(wd_pids)" ]; then
    return 0
  fi
  WD="$MODDIR/watchdog.sh"
  [ -f "$WD" ] || return 1

  if command -v setsid >/dev/null 2>&1; then
    setsid sh "$WD" >/dev/null 2>&1 &
  else
    sh "$WD" >/dev/null 2>&1 &
  fi

  # 等它出现在进程表里，再回写 pid（watchdog.sh 自己也写一份，两边一致）
  i=0
  while [ "$i" -lt 8 ]; do
    sleep 1
    p=$(wd_pids | head -n 1)
    if [ -n "$p" ]; then
      echo "$p" > "$WD_PID_FILE"
      return 0
    fi
    i=$((i + 1))
  done
  return 1
}

do_status() {
  load_conf
  if running; then
    echo "状态: 运行中 (pid $(gw_pid))"
  else
    echo "状态: 未运行"
  fi
  if [ -n "$(wd_pids)" ]; then
    echo "守护循环: 运行中 (pid $(wd_pids | tr '\n' ' '))"
  else
    echo "守护循环: 未运行（进程崩溃后不会自动恢复）"
  fi
  echo "监听: $HOST:$PORT"

  # 探活：/health 是免鉴权端点。
  # 优先 curl（真正发 HTTP 请求），没有就用 netstat 看端口在不在听
  # （mksh 没有 /dev/tcp，别指望 sh 内建做 TCP 连接）。
  if command -v curl >/dev/null 2>&1; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null)
  else
    code=$(probe_tcp "$PORT")
  fi
  if [ -n "$code" ] && [ "$code" != "000" ]; then
    echo "健康检查: HTTP $code"
  else
    echo "健康检查: 不通"
  fi

  # 检查真实 bind 地址是否与配置一致（防止「配置对了但进程没换」）
  # netstat -tlnp 行格式：Proto Recv-Q Send-Q Local Foreign State PID/Name
  # 本地地址是第 4 列。注意：
  #   - 部分 ROM 的 netstat 输出带 CR，要先 tr 掉；
  #   - mksh 的 grep 不一定支持 [[:space:]]，所以用字面匹配 + 空白归一。
  real=$(netstat -tlnp 2>/dev/null \
    | tr -d '\r' \
    | grep 'LISTEN' \
    | grep ":$PORT " \
    | head -n 1 \
    | sed 's/^[[:space:]]*//' \
    | sed 's/[[:space:]][[:space:]]*/ /g' \
    | cut -d' ' -f4 \
    | sed "s/:$PORT\$//")
  if [ -n "$real" ] && [ "$real" != "$HOST" ]; then
    echo "⚠️  实际监听 $real，与配置 $HOST 不一致（进程未按新配置重启）"
    echo "    修复: sh $0 restart"
  fi

  # 局域网地址：HOST=0.0.0.0 时把本机 IP 打出来，方便手机之外的设备访问
  if [ "$HOST" = "0.0.0.0" ]; then
    ip=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -n 1)
    if [ -z "$ip" ]; then
      ip=$(ip -4 addr show wlan0 2>/dev/null | sed -n 's/.*inet \([0-9.]*\).*/\1/p' | head -n 1)
    fi
    [ -n "$ip" ] && echo "局域网: http://$ip:$PORT/"
  fi

  echo "数据目录: $DATA_DIR"
  echo "配置文件: $CONF"
  echo "日志: $LOG_DIR/gateway.log"
  if [ -f "$DATA_DIR/agent2api.db" ]; then
    echo "数据库: $(du -h "$DATA_DIR/agent2api.db" 2>/dev/null | cut -f1)"
  fi

  # 插件状态：v3.4.0 起 provider 实现全在插件里，
  # 没插件时账号页空白、/v1 报 503 —— 这个必须能一眼看到。
  if [ -n "$(px_bin)" ]; then
    if [ -n "$(px_pids)" ]; then
      echo "提供商插件: 已装载 (宿主 pid $(px_pids | tr '\n' ' '))"
    else
      echo "提供商插件: 已铺设，宿主未运行（网关可能还在启动）"
    fi
  else
    echo "提供商插件: ❌ 未铺设 —— 执行 sh $0 plugins 重新铺设"
  fi
}

# ── 插件铺设 ────────────────────────────────────────────────
# 手动补铺（正常由 service.sh 开机时调 plugin-setup.sh）
do_plugins() {
  PS="$MODDIR/plugin-setup.sh"
  if [ ! -f "$PS" ]; then
    echo "错误：找不到 $PS"
    return 1
  fi
  chmod 755 "$PS" 2>/dev/null
  sh "$PS"
  echo "插件文件："
  b=$(px_bin)
  if [ -n "$b" ]; then
    ls -l "$b"
  else
    echo "  未找到（铺设失败，看 $DATA_DIR/logs/plugin-setup.log）"
  fi
  if [ -f "$DATA_DIR/plugins/plugins.json" ]; then
    if grep -q '"agent2api-providers"' "$DATA_DIR/plugins/plugins.json" 2>/dev/null; then
      echo "注册表: 已登记"
    else
      echo "注册表: ❌ 未登记"
    fi
  else
    echo "注册表: ❌ 不存在"
  fi
  echo ""
  echo "重启网关让插件生效: sh $0 restart"
}

# ── 局域网开关 ──────────────────────────────────────────────
# 手改 module.conf 容易改错位置（比如改到注释行），这里做成一个命令。
do_lan() {
  case "$2" in
    on|1|open)   new="0.0.0.0" ;;
    off|0|close) new="127.0.0.1" ;;
    *)
      load_conf
      echo "当前: HOST=$HOST"
      echo "用法: $0 lan on|off"
      return 1
      ;;
  esac

  [ -f "$CONF" ] || { echo "错误：找不到 $CONF，请先启动一次生成配置"; return 1; }

  if grep -q '^HOST=' "$CONF"; then
    sed -i "s/^HOST=.*/HOST=$new/" "$CONF"
  else
    echo "HOST=$new" >> "$CONF"
  fi

  echo "HOST 已设为 $new"
  if [ "$new" = "0.0.0.0" ]; then
    echo "⚠️  面板与接口将暴露给同一局域网内的所有设备"
    echo "    请确认已注册管理员并创建 API Key（ALLOW_NO_KEY 保持 0）"
  fi

  # 必须连守护循环一起重启，否则它会用旧 HOST 把网关拉回来。
  # do_start 内部已经负责重建 watchdog 并等端口真正 bind，这里不用再调一次
  # （再调一次是空跑：wd_pids 非空就直接返回，但会让输出看起来起了两个）。
  stop_watchdog
  stop_gateway
  echo ""
  do_start

  echo ""
  real=$(netstat -tlnp 2>/dev/null \
    | tr -d '\r' \
    | grep 'LISTEN' \
    | grep ":$PORT " \
    | head -n 1 \
    | sed 's/^[[:space:]]*//' \
    | sed 's/[[:space:]][[:space:]]*/ /g' \
    | cut -d' ' -f4 \
    | sed "s/:$PORT\$//")
  echo "实际监听: ${real:-未知}"
}

case "$1" in
  # do_start 内部已经管 watchdog 的启停，这里不用再调一次
  start) do_start ;;
  stop) do_stop ;;
  # do_start 内部已负责重建 watchdog 并等端口 bind，这里不要再调 do_watchdog
  restart) do_stop; sleep 1; do_start ;;
  status) do_status ;;
  lan) do_lan "$@" ;;
  plugins) do_plugins ;;
  watchdog) do_watchdog ;;
  log|logs) tail -n "${2:-60}" "$LOG_DIR/gateway.log" ;;
  config) load_conf; cat "$CONF" ;;
  port) load_conf; echo "$PORT" ;;
  *)
    echo "用法: $0 {start|stop|restart|status|log [行数]|config|port|lan on|off|plugins|watchdog}"
    exit 1
    ;;
esac
