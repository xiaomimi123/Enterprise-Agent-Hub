#!/usr/bin/env bash
# 提交前本地跑一遍和 CI 相同的检查（后端测试、前端类型检查和 lint、接入器语法）。
# Windows 上用 Git Bash 运行：bash tools/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=console/backend/.venv/Scripts/python
[ -x "$PY" ] || PY=console/backend/.venv/bin/python

echo "== 后端测试"
(cd console/backend && "../../$PY" -m pytest -q)

echo "== 前端类型检查、lint 与冒烟测试"
(cd console/frontend && npx tsc -b && npx oxlint src && npm test)

echo "== 接入器语法"
"$PY" -m py_compile agent/hub_agent.py

echo "全部通过（安装脚本相关的 agent/tests/*.mjs 只在 Windows 上跑：node agent/tests/<名字>.mjs）"
