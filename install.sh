#!/bin/bash
# 安装/更新 Kindle 墨水屏看板
#
# 用法：bash install.sh
#
# 做的事：
#   1. 用仓库里的 plist 模板生成 4 个 LaunchAgent（路径自动填当前项目位置）
#   2. 卸载同名旧任务后重新加载
#   3. 验证 8077 图床服务起来
#
# ⚠️ 注意：本项目位于 ~/Downloads 下，macOS TCC 会把 /bin/sh、/bin/bash 视为
#    "Platform Binary" 直接拒绝（exit 126）。因此所有常驻入口都是 .py，
#    由 Python.framework 的 python3 执行。plist 里不要改回 shell。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"

# 选 Python：Python.framework 优先（不受 Downloads 的 TCC 限制），
# 其次 Homebrew / 系统 python3。
PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
         /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         "$(command -v python3 || true)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then PY="$c"; break; fi
done

LABELS=(
  com.proma.kindle-dash-server
  com.proma.kindle-dash-watchdog
  com.proma.kindle-quota-render
  com.proma.kindle-timelog
)

if [ -z "$PY" ]; then
  echo "❌ 找不到 python3"
  echo "   推荐装 Python 3.12（python.org 版）：它不受 ~/Downloads 的 TCC 限制"
  exit 1
fi

echo "项目根目录: $ROOT"
mkdir -p "$ROOT/data/pages" "$ROOT/data/timelog" "$ROOT/data/reports" "$ROOT/launchd"

# 生成 plist（路径写死当前实际位置；项目移动后重跑本脚本即可）
echo "→ 生成 LaunchAgent 配置"
"$PY" - "$ROOT" "$PY" <<'PYEOF'
import os, plistlib, sys
ROOT, PYBIN = sys.argv[1], sys.argv[2]
defs = {
 "com.proma.kindle-dash-server": {
   "Label": "com.proma.kindle-dash-server",
   "ProgramArguments": [PYBIN, f"{ROOT}/bin/serve.py"],
   "WorkingDirectory": f"{ROOT}/data",
   "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
   "StandardOutPath": f"{ROOT}/data/serve-stdout.log",
   "StandardErrorPath": f"{ROOT}/data/serve-stderr.log"},
 "com.proma.kindle-dash-watchdog": {
   "Label": "com.proma.kindle-dash-watchdog",
   "ProgramArguments": [PYBIN, f"{ROOT}/bin/watchdog.py"],
   "StartInterval": 60, "RunAtLoad": True, "AbandonProcessGroup": True},
 "com.proma.kindle-quota-render": {
   "Label": "com.proma.kindle-quota-render",
   "ProgramArguments": [PYBIN, f"{ROOT}/bin/render_all.py"],
   "StartInterval": 300, "RunAtLoad": True,
   "StandardOutPath": "/tmp/kindle-render.log",
   "StandardErrorPath": "/tmp/kindle-render.log"},
 "com.proma.kindle-timelog": {
   "Label": "com.proma.kindle-timelog",
   "ProgramArguments": [PYBIN, f"{ROOT}/bin/time_logger.py"],
   "StartInterval": 60, "RunAtLoad": True},
}
for name, d in defs.items():
    with open(os.path.join(ROOT, "launchd", f"{name}.plist"), "wb") as f:
        plistlib.dump(d, f)
PYEOF

# 先卸载旧任务
for L in "${LABELS[@]}"; do
  launchctl unload "$AGENTS/$L.plist" 2>/dev/null || true
done
sleep 1

# 安装并加载
echo "→ 安装到 $AGENTS"
for L in "${LABELS[@]}"; do
  cp "$ROOT/launchd/$L.plist" "$AGENTS/$L.plist"
  launchctl load "$AGENTS/$L.plist"
  echo "  ✅ $L"
done

sleep 4

# 验证
echo "→ 验证 8077 图床"
CODE=$(curl -s -m 6 -o /dev/null -w "%{http_code}" http://127.0.0.1:8077/quota.png || echo 000)
if [ "$CODE" = "200" ]; then
  echo "  ✅ HTTP 200，图床正常"
else
  echo "  ⚠️ HTTP $CODE，检查 data/serve-stderr.log"
fi

echo
echo "完成。服务状态："
launchctl list | grep kindle || true
echo
echo "调试："
echo "  日志   $ROOT/data/server.log"
echo "  渲染   /tmp/kindle-render.log"
echo "  手动跑 $PY $ROOT/bin/watchdog.py"
