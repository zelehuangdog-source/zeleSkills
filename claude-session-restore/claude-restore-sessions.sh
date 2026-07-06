#!/bin/bash
# 重启后手动运行：读取 claude-session-snapshot.sh 生成的 manifest，
# 依次打开对应的 Warp Tab Config，恢复每个 claude 会话。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/claude-restore-manifest.txt"
MANIFEST_META="$SCRIPT_DIR/claude-restore-manifest.meta"

if [ ! -s "$MANIFEST" ]; then
  echo "manifest 不存在或为空：$MANIFEST（请先在重启前运行 claude-session-snapshot.py）" >&2
  exit 1
fi

if [ -s "$MANIFEST_META" ]; then
  saved_at=$(cat "$MANIFEST_META")
  echo "这份存档的时间：$saved_at"
else
  echo "警告：找不到存档时间戳（可能是旧版本存档），无法判断新鲜度" >&2
fi

echo "开始恢复 Warp tab..."
n=0
while IFS= read -r name; do
  [ -z "$name" ] && continue
  n=$((n + 1))
  echo "  [$n] 打开 $name"
  open "warp://tab_config/$name"
  sleep 0.4
done < "$MANIFEST"

echo "完成，共恢复 $n 个 tab"
