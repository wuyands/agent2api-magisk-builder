#!/system/bin/sh
# 提供商插件铺设（幂等，每次开机都会跑）
#
# 为什么需要这一步：
#   v3.4.0 起网关把所有 provider 实现搬进了独立进程插件包。
#   没装插件时 `is_executable_provider()` 恒为 false，
#   于是账号页把 10 个账号全判成 `not_installed` 隐藏，
#   /v1 调用直接 503「没有可用账号」——
#   模块必须自带插件包，否则装完是个空壳。
#
# 铺设 = 两件事：
#   1. plugin-pack/ 复制到 /data/adb/agent2api/plugins/agent2api-providers/<ver>/
#   2. 在 /data/adb/agent2api/plugins/plugins.json 里登记这个包
#
# 为什么注册表要预生成：
#   Android 上没有 python/jq，用 shell 解析 34 个 provider 的 JSON 数组不现实。
#   注册表结构装好之后是静态的，所以桌面端用 gen-registry.py 算好
#   （plugin-registry/registry-entry.json 是单行），模块端只做插入。
#
# 幂等 / 不越权规则：
#   - 注册表里已有本包且版本一致 → 只补文件（缺了才补），不动注册表
#   - 注册表里已有本包且版本更高 → 一律不动（用户在面板升级过，模块不能降级）
#   - 注册表里已有本包但版本更低 → 照常铺新版本目录，并把注册表里这条整条替换
#     （这是模块自身升级的主路径：v3.4.0 → v3.4.1 不能因为「版本不等」就跳过，
#      否则新提供商永远进不来）
#   - 注册表不存在 → 整份写入预生成模板
#   - 注册表存在但没有本包 → 把单行条目插到 "packs": [ 之后

MODDIR=${0%/*}
DATA_DIR=/data/adb/agent2api
PLUG_DIR="$DATA_DIR/plugins"
PACK_ID=agent2api-providers
PACK_VER=3.5.0-beta.3
SRC="$MODDIR/plugin-pack"
REG_DIR="$MODDIR/plugin-registry"
DEST="$PLUG_DIR/$PACK_ID/$PACK_VER"
REG="$PLUG_DIR/plugins.json"
BIN="$DEST/bin/agent2api-providers"
LOG="$DATA_DIR/logs/plugin-setup.log"

log() { echo "[plugin] $(date '+%F %T') $*" >> "$LOG" 2>/dev/null; }

[ -d "$SRC" ] || exit 0
[ -f "$SRC/pack.json" ] || exit 0

mkdir -p "$PLUG_DIR" "$DATA_DIR/logs" 2>/dev/null

# 注册表里本包的版本号（取不到就是空）
reg_version() {
  [ -f "$REG" ] || return 0
  grep -q "\"id\"[[:space:]]*:[[:space:]]*\"$PACK_ID\"" "$REG" 2>/dev/null || return 0
  sed -n "/\"$PACK_ID\"/,/\"manifest_providers\"/p" "$REG" 2>/dev/null \
    | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    | head -n 1
}

# 版本比较：$1 > $2 返回 0。
#
# 先按 x.y.z 逐段比数字（缺位补 0），三段全相等时再看预发布后缀
# （`3.5.0-beta.3` 里的 `-beta.3`）：
#
#   · 都没有后缀            → 相等，不算更高
#   · 左边没有、右边有      → 左边更高（正式版 > 同号预发布）
#   · 左边有、右边没有      → 左边更低
#   · 都有后缀              → 比后缀里最大的数字段（beta.10 > beta.7，数字比不是字符串比）
#
# 后缀这一层是必须的：模块走 beta 通道时 PACK_VER 会带 `-beta.N`，
# 而用户面板里可能已经装了同号的正式版。旧实现把两边的第三段都当成 0，
# 于是「正式版 3.5.0」会被判成不比「beta.3」高，升级路径把正式版降级成预发布。
#
# 不用 sort -V —— Android 的 toybox sort 不保证支持它。
ver_stage() {
  # 后缀里最大的数字段；没有后缀返回 100（正式版恒大于同号预发布）
  _vs_pre=${1#*-}
  if [ "$_vs_pre" = "$1" ]; then printf '%s\n' 100; return 0; fi
  _vs_max=0
  _vs_rest=$_vs_pre
  while [ -n "$_vs_rest" ]; do
    _vs_piece=${_vs_rest%%.*}
    _vs_piece=${_vs_piece%%-*}
    case "$_vs_piece" in
      ''|*[!0-9]*) : ;;
      *) [ "$_vs_piece" -gt "$_vs_max" ] && _vs_max=$_vs_piece ;;
    esac
    case "$_vs_rest" in
      *.*) _vs_rest=${_vs_rest#*.} ;;
      *) break ;;
    esac
  done
  printf '%s\n' "$_vs_max"
}

ver_gt() {
  _va=$1
  _vb=$2
  _vi=1
  while [ "$_vi" -le 3 ]; do
    _vx=$(printf '%s' "${_va%%-*}" | cut -d. -f"$_vi")
    _vy=$(printf '%s' "${_vb%%-*}" | cut -d. -f"$_vi")
    case "$_vx" in ''|*[!0-9]*) _vx=0 ;; esac
    case "$_vy" in ''|*[!0-9]*) _vy=0 ;; esac
    if [ "$_vx" -gt "$_vy" ]; then return 0; fi
    if [ "$_vx" -lt "$_vy" ]; then return 1; fi
    _vi=$((_vi + 1))
  done
  # 三段相等：比预发布后缀
  _sa=$(ver_stage "$_va")
  _sb=$(ver_stage "$_vb")
  if [ "$_sa" -gt "$_sb" ]; then return 0; fi
  return 1
}

# 注册表外壳是否还完整：必须是 `{` 开头、且还带着 `"packs"` 键。
#
# 为什么单独查这一条：上一版模块的升级路径靠「向前找独立成行的 `{`」定位包对象，
# 遇到把元素压成一行的紧凑注册表会**误抓到最外层那个 `{`**，于是整个
# `{"packs":[...]}` 被一条裸的 pack 对象替换掉。网关 load() 解析失败后按空表
# 处理 —— 表现就是「插件文件都在、目录也对，但一家提供商都不出现」，
# 而且日志里没有任何报错。这种形状救不回来，只能按模板重建。
#
# 注意这里**不**检查本包在不在：注册表合法但装着别的包是正常状态。
registry_ok() {
  [ -f "$REG" ] || return 1
  [ -s "$REG" ] || return 1
  head -c 1 "$REG" 2>/dev/null | grep -q '{' || return 1
  grep -q '"packs"' "$REG" 2>/dev/null || return 1
  return 0
}

registered=$(reg_version)

# 外壳坏了（见 registry_ok 的说明）：备份成 .broken 后删掉，让它走下面的
# 「注册表不存在 → 整份写模板」分支。代价只是用户对单个提供商的手工开关回到
# 默认值，比整个插件静默失效强得多。
if [ -f "$REG" ] && ! registry_ok; then
  cp "$REG" "$REG.broken" 2>/dev/null
  rm -f "$REG" 2>/dev/null
  registered=""
  log "注册表外壳不可用（缺 packs 键或被压成单条）—— 已备份为 plugins.json.broken，按模板重建"
fi
if [ -n "$registered" ] && ver_gt "$registered" "$PACK_VER"; then
  # 注册表里是更高的版本：用户在面板里升级过，模块不能把它降下来
  log "注册表已是 v$registered（高于模块自带 v$PACK_VER）—— 跳过（不降级）"
  exit 0
fi
if [ -n "$registered" ] && [ "$registered" != "$PACK_VER" ]; then
  log "注册表是 v$registered，模块自带 v$PACK_VER —— 走升级路径"
fi

# ── 1. 铺插件文件 ───────────────────────────────────────────
if [ -f "$BIN" ] && [ -f "$DEST/pack.json" ]; then
  : # 已就位
else
  TMP="$PLUG_DIR/.staging-$PACK_ID"
  rm -rf "$TMP" 2>/dev/null
  if cp -a "$SRC" "$TMP" 2>/dev/null || cp -R "$SRC" "$TMP" 2>/dev/null; then
    chmod 0755 "$TMP/bin/agent2api-providers" 2>/dev/null
    mkdir -p "$PLUG_DIR/$PACK_ID" 2>/dev/null
    rm -rf "$DEST" 2>/dev/null
    if mv "$TMP" "$DEST" 2>/dev/null; then
      :
    else
      mkdir -p "$DEST" 2>/dev/null
      cp -a "$TMP/." "$DEST/" 2>/dev/null
      rm -rf "$TMP" 2>/dev/null
    fi
    log "已铺设 $PACK_ID v$PACK_VER → $DEST"
  else
    rm -rf "$TMP" 2>/dev/null
    log "铺设失败（无法复制 $SRC）"
    exit 0
  fi
fi
chmod 0755 "$BIN" 2>/dev/null

# 清掉本包的旧版本目录：同一个包不会同时跑两个版本，留着白占 10MB。
# 判据必须是「像版本目录」（有 pack.json 或入口二进制），
# 因为 $PLUG_DIR/$PACK_ID/ 下还可能有 qoder-machine-id 这类数据目录。
for old in "$PLUG_DIR/$PACK_ID"/*/; do
  [ -d "$old" ] || continue
  oldname=${old%/}
  oldname=${oldname##*/}
  [ "$oldname" = "$PACK_VER" ] && continue
  [ -f "$old/pack.json" ] || [ -f "$old/bin/agent2api-providers" ] || continue
  rm -rf "$old" 2>/dev/null && log "清理旧版本目录 $oldname"
done

# ── 2. 登记到 plugins.json ──────────────────────────────────
if [ -n "$registered" ] && [ "$registered" = "$PACK_VER" ]; then
  exit 0   # 版本一致且已在册，文件也补过了
fi

entry=""
[ -f "$REG_DIR/registry-entry.json" ] && entry=$(tr -d '\r' < "$REG_DIR/registry-entry.json" 2>/dev/null | head -n 1)
[ -z "$entry" ] && { log "缺少 registry-entry.json，跳过注册"; exit 0; }

# 注册表里已有本包但版本更低（模块升级）：把这一整条换成新的单行条目。
# 为什么不只改 version 字段：manifest_providers 与 providers 布尔表也要跟着
# 换成新版本的 34 家，否则新提供商在 pack.json 读不到时会回落成旧的 32 家。
if [ -n "$registered" ]; then
  cp "$REG" "$REG.bak" 2>/dev/null
  upgrade_tmp="$REG.upgrade"

  idline=$(grep -n "\"id\"[[:space:]]*:[[:space:]]*\"$PACK_ID\"" "$REG" 2>/dev/null \
    | head -n 1 | cut -d: -f1)
  case "$idline" in
    ''|*[!0-9]*)
      log "找不到本包所在行，保留原注册表"
      exit 0
      ;;
  esac

  # 向前找包对象的起始行（去掉缩进后恰好是 { 的那一行）。
  #
  # 两个必须的限制，都是踩过的坑：
  #   ① 只在本包的 id 行与 packs 键之间找 —— 否则会一路往上抓到最外层那个 {，
  #      把整个 {"packs":[...]} 换成一条裸条目。那种文件网关解析失败后按空表
  #      处理，表现是「插件文件都在、目录也对，但一家提供商都不出现」，而且
  #      日志里没有任何报错；
  #   ② 起点的缩进必须比 packs 行深，作为第二道闸（紧凑注册表里没有独立的
  #      { 行，那种形状由上面的外壳检查拦下，走不到这里）。
  packs_at=$(grep -n '"packs"' "$REG" 2>/dev/null | head -n 1 | cut -d: -f1)
  case "$packs_at" in ''|*[!0-9]*) packs_at=1 ;; esac
  packs_indent=$(sed -n "${packs_at}p" "$REG" 2>/dev/null | sed 's/[^[:space:]].*$//')

  startline=$(tail -n +$((packs_at + 1)) "$REG" 2>/dev/null \
    | head -n $((idline - packs_at)) \
    | grep -n '^[[:space:]]*{[[:space:]]*$' \
    | tail -n 1 | cut -d: -f1)
  if [ -n "$startline" ]; then
    startline=$((startline + packs_at))
  fi
  case "$startline" in
    ''|*[!0-9]*)
      log "找不到本包对象起始行，保留原注册表"
      exit 0
      ;;
  esac
  indent=$(sed -n "${startline}p" "$REG" 2>/dev/null | sed 's/[^[:space:]].*$//')
  if [ "${#indent}" -le "${#packs_indent}" ]; then
    log "包对象起始行缩进不深于 packs 行（疑似抓到外层对象）—— 保留原注册表"
    exit 0
  fi

  # 向后找对象结束行（同一缩进 + } ，可能带逗号）
  endrel=$(tail -n +$((startline + 1)) "$REG" 2>/dev/null \
    | grep -n "^${indent}}[,]*$" \
    | head -n 1 | cut -d: -f1)
  case "$endrel" in
    ''|*[!0-9]*)
      log "找不到本包对象结束行，保留原注册表"
      exit 0
      ;;
  esac
  endline=$((startline + endrel))

  # 末元素没有逗号时，替换进来的条目也不能带逗号
  endtext=$(sed -n "${endline}p" "$REG" 2>/dev/null)
  case "$endtext" in
    *,*) entry_comma="$entry," ;;
    *)   entry_comma="$entry" ;;
  esac

  {
    head -n $((startline - 1)) "$REG" 2>/dev/null
    printf '%s%s\n' "$indent" "$entry_comma"
    tail -n +$((endline + 1)) "$REG" 2>/dev/null
  } > "$upgrade_tmp" 2>/dev/null

  # 校验：非空、首行有 {、末行有 }、本包版本已经是 PACK_VER、JSON 里的 packs 还在
  if [ -s "$upgrade_tmp" ] \
     && head -n 1 "$upgrade_tmp" | grep -q '{' \
     && tail -n 5 "$upgrade_tmp" | grep -q '}' \
     && grep -q '"packs"' "$upgrade_tmp" \
     && grep -q "\"version\"[[:space:]]*:[[:space:]]*\"$PACK_VER\"" "$upgrade_tmp"; then
    mv "$upgrade_tmp" "$REG" 2>/dev/null
    log "已把注册表里的 $PACK_ID 从 v$registered 替换为 v$PACK_VER（第 $startline-$endline 行）"
  else
    rm -f "$upgrade_tmp" 2>/dev/null
    log "替换后校验失败，保留原注册表（v$registered）"
  fi
  exit 0
fi

# 注册表不存在：整份写模板
if [ ! -f "$REG" ]; then
  if [ -f "$REG_DIR/plugins.json" ]; then
    cp "$REG_DIR/plugins.json" "$REG" 2>/dev/null && log "写入新注册表（模板）"
  fi
  exit 0
fi

cp "$REG" "$REG.bak" 2>/dev/null

# 定位 "packs" 所在行
packs_line=$(grep -n '"packs"' "$REG" 2>/dev/null | head -n 1 | cut -d: -f1)
case "$packs_line" in
  ''|*[!0-9]*)
    log "注册表里找不到 packs 键，保留原文件"
    exit 0
    ;;
esac

packs_text=$(sed -n "${packs_line}p" "$REG" 2>/dev/null)
tmp="$REG.new"
: > "$tmp" 2>/dev/null || { log "无法写临时文件"; exit 0; }

# 两种写法都要处理：
#   (a) 多行模板   "packs": [          ← 这一行以 [ 结尾，元素在后面的行里
#   (b) 空数组同行 "packs": []         ← 整个数组就在这一行
# 之前只处理了 (a)，遇到 (b) 会把条目插到 ] 的**后面**，生成
#   "packs": []
#     {"id":...},
#   }
# 这种非法 JSON —— 网关 load() 解析失败后按空表处理，账号又全隐藏。
# 所以这里先看这一行里有没有 ]，有就整行重写成三行。
case "$packs_text" in
  *\]*)
    prefix=${packs_text%%\[*}
    suffix=${packs_text##*\]}
    # [ 与 ] 之间的内容（已存在的包），去掉首尾空白
    inner=${packs_text#*\[}
    inner=${inner%\]*}
    inner=$(printf '%s' "$inner" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    head -n $((packs_line - 1)) "$REG" > "$tmp" 2>/dev/null
    if [ -z "$inner" ]; then
      printf '%s[\n    %s\n  ]%s\n' "$prefix" "$entry" "$suffix" >> "$tmp"
    else
      printf '%s[%s,\n    %s\n  ]%s\n' "$prefix" "$inner" "$entry" "$suffix" >> "$tmp"
    fi
    tail -n +$((packs_line + 1)) "$REG" >> "$tmp" 2>/dev/null
    log "注册表 packs 数组与键写在同一行，已重写为多行并插入"
    ;;
  *)
    # 多行写法：packs 之后第一个非空行如果是 "]" 说明数组为空，
    # 空数组里插值不能带逗号（[x,] 非法）
    next=$(tail -n +$((packs_line + 1)) "$REG" 2>/dev/null \
      | grep -v '^[[:space:]]*$' \
      | head -n 1 \
      | sed 's/^[[:space:]]*//')
    case "$next" in
      ']'*) comma="" ;;
      *)    comma="," ;;
    esac
    sed -n "1,${packs_line}p" "$REG" >> "$tmp" 2>/dev/null
    printf '    %s%s\n' "$entry" "$comma" >> "$tmp"
    tail -n +$((packs_line + 1)) "$REG" >> "$tmp" 2>/dev/null
    ;;
esac

# 校验：文件非空、首行有 {、末尾有 }，且 packs 那一行现在以 [ 结尾
# （如果重写逻辑出错，packs 行会是 "packs": [] —— 那就是把条目插到数组外了，
#  这种非法 JSON 网关会当空表处理，账号又全隐藏，所以必须挡住）
new_packs_line=$(sed -n "${packs_line}p" "$tmp" 2>/dev/null)
case "$new_packs_line" in
  *\[) ok_packs=1 ;;
  *)   ok_packs=0 ;;
esac
if [ -s "$tmp" ] && head -n 1 "$tmp" | grep -q '{' \
   && tail -n 5 "$tmp" | grep -q '}' && [ "$ok_packs" = "1" ]; then
  mv "$tmp" "$REG" 2>/dev/null
  log "已把 $PACK_ID 插入现有注册表（packs 行 $packs_line）"
else
  rm -f "$tmp" 2>/dev/null
  log "插入后校验失败（packs 行未以 [ 结尾），保留原文件"
fi

exit 0
