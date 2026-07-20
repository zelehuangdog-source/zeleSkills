#!/bin/bash
# 重启后手动运行：从 claude-session-snapshot.py 生成的多份存档里挑一份恢复。
#   claude-restore-sessions.sh --list          列出所有存档（最新在前）
#   claude-restore-sessions.sh <snapshot-id>   恢复指定存档
#   claude-restore-sessions.sh latest          恢复最新一份存档
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOTS_DIR="$SCRIPT_DIR/snapshots"

# 列出有效存档的 sid（纯数字目录且 manifest 非空），最新在前
snapshot_ids() {
  [ -d "$SNAPSHOTS_DIR" ] || return 0
  ls -1 "$SNAPSHOTS_DIR" 2>/dev/null | grep -E '^[0-9]+$' | sort -r | while IFS= read -r sid; do
    [ -s "$SNAPSHOTS_DIR/$sid/manifest.txt" ] && echo "$sid"
  done
}

list_snapshots() {
  local found=0
  while IFS= read -r sid; do
    [ -z "$sid" ] && continue
    found=1
    local meta="$SNAPSHOTS_DIR/$sid/meta.txt"
    local time sessions tabs
    time=$(sed -n '1p' "$meta" 2>/dev/null)
    sessions=$(sed -n '2p' "$meta" 2>/dev/null)
    tabs=$(sed -n '3p' "$meta" 2>/dev/null)
    printf '%s\t%s\t%s 个会话\t%s 个 tab\n' "$sid" "${time:-未知时间}" "${sessions:-?}" "${tabs:-?}"
  done < <(snapshot_ids)
  if [ "$found" -eq 0 ]; then
    echo "没有任何存档，请先在重启前运行 claude-session-snapshot.py" >&2
    exit 1
  fi
}

restore_snapshot() {
  local sid="$1"
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

  echo "开始恢复 Warp tab..."
  n=0
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    n=$((n + 1))
    echo "  [$n] 打开 $name"
    open "warp://tab_config/$name"
    sleep 0.4
  done < "$manifest"

  echo "完成，共恢复 $n 个 tab"
}

case "${1:-}" in
  --list | -l | list)
    list_snapshots
    ;;
  "")
    echo "用法: $0 --list | <snapshot-id> | latest" >&2
    exit 2
    ;;
  *)
    restore_snapshot "$1"
    ;;
esac
