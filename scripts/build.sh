#!/usr/bin/env bash
# 把上游网关 + 提供商插件编成两个 Android arm64 二进制。
#
# 平台差异全部收在这里：
#   · CI（ubuntu）用 NDK 的 clang 直连，TMPDIR 本来就是 POSIX 路径；
#   · 本地 Windows/msys 下 clang.exe 是原生程序，TMP 必须是 `cygpath -w` 出来的
#     路径，且 CARGO_TARGET_DIR 不能带空格（ring 的 .S 汇编会失败）。
#
# 用法：
#   scripts/build.sh server   <上游 src-tauri 目录>  <产物输出路径>
#   scripts/build.sh providers <插件仓库目录>        <产物输出路径>
set -euo pipefail

WHAT="${1:?用法: build.sh server|providers <源码目录> <产物输出路径>}"
SRC="${2:?缺少源码目录}"
OUT="${3:?缺少产物输出路径}"

API="${API:-26}"
TRIPLE="aarch64-linux-android"

# cargo 不一定在 PATH 里：CI 的 rust-toolchain action 会放好，本地 Windows
# 装了 rustup 但没把 ~/.cargo/bin 加进 msys 的 PATH。只补这一条，不动别的。
if ! command -v cargo >/dev/null 2>&1; then
  if [ -x "$HOME/.cargo/bin/cargo" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  fi
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "✗ 找不到 cargo（PATH 里没有，$HOME/.cargo/bin 里也没有）" >&2
  exit 1
fi

NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
if [ -z "$NDK" ] || [ ! -d "$NDK" ]; then
  echo "✗ 找不到 Android NDK（ANDROID_NDK_HOME / ANDROID_NDK_ROOT 都没指到目录）" >&2
  exit 1
fi

# NDK 的 host 前缀：CI 是 linux-x86_64，本地可能是 windows-x86_64
HOST_TAG=""
for tag in linux-x86_64 darwin-x86_64 windows-x86_64; do
  if [ -d "$NDK/toolchains/llvm/prebuilt/$tag" ]; then HOST_TAG="$tag"; break; fi
done
if [ -z "$HOST_TAG" ]; then
  echo "✗ NDK 里没有可用的 llvm prebuilt（找过 linux/darwin/windows-x86_64）" >&2
  exit 1
fi
BIN="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin"

# clang 后缀：Windows 上是 .cmd 包装脚本，其它平台没有后缀。
# 注意 llvm-ar / llvm-ranlib 在同一目录下是 .exe，不加 .cmd ——
# 加了会拿到一个跑不通的包装，ring 的静态库打包当场失败（exit 1 且没 stderr）。
CLANG_SUF=""
AR_SUF=""
case "$HOST_TAG" in windows-*) CLANG_SUF=".cmd" ;; esac

# Windows/msys：这些工具是原生 Windows 程序，路径得给成 C:\... 形式
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) BIN="$(cygpath -w "$BIN")" ;;
esac

export CC_aarch64_linux_android="$BIN/aarch64-linux-android${API}-clang${CLANG_SUF}"
export CXX_aarch64_linux_android="$BIN/aarch64-linux-android${API}-clang++${CLANG_SUF}"
export AR_aarch64_linux_android="$BIN/llvm-ar${AR_SUF}"
export RANLIB_aarch64_linux_android="$BIN/llvm-ranlib${AR_SUF}"
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$CC_aarch64_linux_android"

# Windows/msys：把 TMP 换成原生路径、产物放无空格目录
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    # clang.exe 是原生程序，不认 msys 的 /tmp；临时目录还得真存在
    _tmp="${TMPDIR:-/c/tmp}"
    mkdir -p "$_tmp"
    export TMP="$(cygpath -w "$_tmp")"
    export TEMP="$TMP"
    export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$(cygpath -w /c/a2abtarget)}"
    ;;
esac

cd "$SRC"

# 本地开发时 git 依赖可能拉不下来（cargo 的 git db 是空壳会卡十分钟），
# 允许用 .cargo/config.toml 的 [patch] 指到本地副本。CI 上不需要，也不会存在。
if [ "$WHAT" = "server" ]; then
  cargo build --release --target "$TRIPLE" -p agent2api-server
  BIN_NAME="agent2api-server"
else
  cargo build --release --target "$TRIPLE" -p agent2api-providers
  BIN_NAME="agent2api-providers"
fi

BUILT="${CARGO_TARGET_DIR:-$(pwd)/target}/$TRIPLE/release/$BIN_NAME"
if [ ! -f "$BUILT" ]; then
  echo "✗ 编完了但找不到产物：$BUILT" >&2
  exit 1
fi
mkdir -p "$(dirname "$OUT")"
cp "$BUILT" "$OUT"
chmod 0755 "$OUT"
echo "  $BIN_NAME → $OUT（$(stat -c%s "$OUT" 2>/dev/null || wc -c < "$OUT") 字节）"
