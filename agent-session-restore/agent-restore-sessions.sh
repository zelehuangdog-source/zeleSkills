#!/bin/bash
# 重启后手动运行：从 agent-session-snapshot.py 生成的多份存档里挑一份恢复。
#   agent-restore-sessions.sh --list                      列出所有存档（最新在前）
#   agent-restore-sessions.sh --agents <snapshot-id>      只报该存档记录的构成（claude / grok 各多少个格子）
#   agent-restore-sessions.sh <snapshot-id> [启动命令]    恢复指定存档
#   agent-restore-sessions.sh latest [启动命令]           恢复最新一份存档
# 启动命令二选一：mc（默认，用 mc --code 启动）/ claude（用 claude 命令启动）。
# 这只作用于存档里 claude 的 pane：恢复前把它们的 resume 命令前缀改写成对应启动方式，
# session_id 不变；grok 的 pane 始终用 grok 命令，不受这个参数影响。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOTS_DIR="$SCRIPT_DIR/snapshots"
TAB_CONFIG_DIR="$HOME/.warp/tab_configs"
GROK_SESSIONS_DIR="$HOME/.grok/sessions"

# 启动命令前缀（都保留 --dangerously-skip-permissions，跟原来的 mc --code 行为对齐）
launcher_prefix() {
  case "$1" in
    claude) echo "claude --dangerously-skip-permissions --resume" ;;
    *) echo "mc --code --dangerously-skip-permissions --resume" ;;
  esac
}

# 改写某个 tab-config 里 claude 的 resume 命令前缀：
# commands = ["mc --code|claude … --resume <session_id>"] → commands = ["<新前缀> --resume <session_id>"]
# 只认 mc / claude 两种前缀，grok 的命令原样不动。
rewrite_launcher() {
  local file="$1" prefix
  prefix="$(launcher_prefix "$2")"
  [ -f "$file" ] || return 0
  sed -i '' -E "s#commands = \\[\"(mc|claude)[^\"]*--resume #commands = [\\\"$prefix #" "$file"
  # 前缀本身已含 --resume，替换后会重复一次，去掉多余的
  sed -i '' -E "s#(--resume[^\"]*)--resume #\1#" "$file"
}

# 判断某个 grok 会话是否还存在：grok 按 cwd 分目录存会话
# （~/.grok/sessions/<URL 编码的 cwd>/<session-id>/），目录不在就没法 resume。
grok_session_exists() {
  python3 - "$1" "$2" <<'PY'
import pathlib
import sys
import urllib.parse

sid, cwd = sys.argv[1], sys.argv[2]
d = pathlib.Path.home() / ".grok" / "sessions" / urllib.parse.quote(cwd, safe="") / sid
sys.exit(0 if d.is_dir() else 1)
PY
}

# 挨行扫 tab-config：记住当前 pane 的 directory，遇到 grok 的 resume 命令就校验会话是否还在；
# 不在就把这条 commands 删掉——那个格子仍然还原（落成一个普通 shell），但不会让你看到一个
# 一启动就报 session not found 的 pane。
prune_missing_grok_sessions() {
  local file="$1" line dir="" sid="" tmp
  [ -f "$file" ] || return 0
  tmp="$(mktemp)"
  while IFS= read -r line; do
    if [[ "$line" =~ ^directory\ =\ \"(.*)\"$ ]]; then
      dir="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^commands\ =\ \[\"grok\ .*--resume\ ([^\"]+)\"\]$ ]]; then
      sid="${BASH_REMATCH[1]}"
      if ! grok_session_exists "$sid" "$dir"; then
        echo "    ! grok 会话 ${sid:0:8} 已不存在（${dir}）：该 pane 降级为普通 shell" >&2
        continue
      fi
    fi
    printf '%s\n' "$line" >> "$tmp"
  done < "$file"
  mv "$tmp" "$file"
}

# 列出有效存档的 sid（纯数字目录且 manifest 非空），最新在前
snapshot_ids() {
  [ -d "$SNAPSHOTS_DIR" ] || return 0
  ls -1 "$SNAPSHOTS_DIR" 2>/dev/null | grep -E '^[0-9]+$' | sort -r | while IFS= read -r sid; do
    [ -s "$SNAPSHOTS_DIR/$sid/manifest.txt" ] && echo "$sid"
  done
}

# 一份存档里各 agent 多少个格子：直接读存档自己记的构成（meta.txt 第 4 行，存档时写死的）。
# 不去翻 ~/.warp/tab_configs/*.toml 现算——那些 toml 会被恢复过程改写启动命令前缀、被删掉
# 失效的 grok commands，读它们等于把"存档构成"变成一个会随时间漂移的外部状态。早期存档没有
# 这一行，只能报"未知"（上层按保守处理：未知就照样问 claude 的启动命令）。
snapshot_agents() {
  local meta="$SNAPSHOTS_DIR/$1/meta.txt" line
  [ -s "$meta" ] || return 1
  line=$(sed -n '4p' "$meta")
  printf '%s' "${line:-未知}"
}

list_snapshots() {
  local found=0
  while IFS= read -r sid; do
    [ -z "$sid" ] && continue
    found=1
    local meta="$SNAPSHOTS_DIR/$sid/meta.txt"
    local time sessions tabs agents
    time=$(sed -n '1p' "$meta" 2>/dev/null)
    sessions=$(sed -n '2p' "$meta" 2>/dev/null)
    tabs=$(sed -n '3p' "$meta" 2>/dev/null)
    agents=$(snapshot_agents "$sid")
    printf '%s\t%s\t%s 个会话\t%s 个 tab\t%s\n' \
      "$sid" "${time:-未知时间}" "${sessions:-?}" "${tabs:-?}" "${agents:-未知}"
  done < <(snapshot_ids)
  if [ "$found" -eq 0 ]; then
    echo "没有任何存档，请先在重启前运行 agent-session-snapshot.py" >&2
    exit 1
  fi
}

restore_snapshot() {
  local sid="$1" launcher="${2:-mc}"
  if [ "$sid" = "latest" ]; then
    sid=$(snapshot_ids | head -n1)
    [ -z "$sid" ] && { echo "没有任何存档可恢复" >&2; exit 1; }
  fi

  local manifest="$SNAPSHOTS_DIR/$sid/manifest.txt"
  local meta="$SNAPSHOTS_DIR/$sid/meta.txt"
  if [ ! -s "$manifest" ]; then
    echo "存档 $sid 不存在或为空：$manifest" >&2
    echo "可用存档：" >&2
    list_snapshots >&2
    exit 1
  fi

  if [ -s "$meta" ]; then
    echo "恢复存档：$(sed -n '1p' "$meta")（ID ${sid}）"
  else
    echo "恢复存档：$sid"
  fi

  echo "开始恢复 Warp tab（claude 的 pane 用 $(launcher_prefix "$launcher") <session_id>，grok 的 pane 用自己的命令）..."
  n=0
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    n=$((n + 1))
    echo "  [$n] 打开 $name"
    rewrite_launcher "$TAB_CONFIG_DIR/$name.toml" "$launcher"
    prune_missing_grok_sessions "$TAB_CONFIG_DIR/$name.toml"
    open "warp://tab_config/$name"
    sleep 0.4
  done < "$manifest"

  echo "完成，共恢复 $n 个 tab"
}

case "${1:-}" in
  --list | -l | list)
    list_snapshots
    ;;
  --agents)
    snapshot_agents "${2:?用法: $0 --agents <snapshot-id>}"
    echo
    ;;
  "")
    echo "用法: $0 --list | --agents <snapshot-id> | <snapshot-id> | latest，可选第二个参数指定 claude 的启动命令：mc（默认）/ claude" >&2
    exit 2
    ;;
  *)
    restore_snapshot "$1" "${2:-}"
    ;;
esac
