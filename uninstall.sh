#!/bin/bash
# 卸载 Kindle 墨水屏看板
#
# 用法：
#   bash uninstall.sh            # 停服务并移除 LaunchAgent，保留 data/ 历史数据
#   bash uninstall.sh --purge    # 连 data/ 一起删（timelog、周报、看板图全部清空）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"

LABELS=(
  com.proma.kindle-dash-server
  com.proma.kindle-dash-watchdog
  com.proma.kindle-quota-render
  com.proma.kindle-timelog
  com.proma.kindle-menubar
)

echo "→ 停止并移除 LaunchAgent"
for L in "${LABELS[@]}"; do
  launchctl unload "$AGENTS/$L.plist" 2>/dev/null || true
  rm -f "$AGENTS/$L.plist"
  echo "  ✅ $L"
done

echo "→ 停掉残留进程"
pkill -f "$ROOT/bin/serve.py" 2>/dev/null || true
pkill -f "$ROOT/bin/watchdog.py" 2>/dev/null || true
pkill -f "$ROOT/bin/menubar.py" 2>/dev/null || true
rm -f "$ROOT/data/.menubar.pid"

if [ "${1:-}" = "--purge" ]; then
  echo "→ 删除运行数据（--purge）"
  rm -rf "$ROOT/data"
  echo "  ✅ data/ 已删除"
else
  echo "→ 保留 $ROOT/data（含时间采集历史与周报）"
  echo "   如需一并删除：bash uninstall.sh --purge"
fi

echo
echo "注意：Kindle 设备上的看板程序仍在运行，会持续尝试拉图失败。"
echo "      如需停掉设备端：ssh root@<kindle-ip> 'pkill -f /tmp/dash.sh'"
