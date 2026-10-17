#!/bin/sh
# 企业智能体中枢 · macOS / Linux 一键接入。由中枢在 /api/agent/install.sh 提供，__HUB_URL__ 会被替换成中枢地址。
# 用法：curl -fsSL http://<中枢>:8088/api/agent/install.sh | sh
# 步骤：没有 uv 就安装 → 下载接入器 → 浏览器登录 → 自动配置 WorkBuddy / Cursor / Claude 桌面版
set -e
HUB='__HUB_URL__'
DIR="$HOME/.hub-agent"

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "[1/3] 安装 uv（Python 运行器）……"
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo "[1/3] uv 已安装"
fi
UV=$(command -v uv || echo "$HOME/.local/bin/uv")

echo "[2/3] 下载接入器……"
mkdir -p "$DIR"
curl -fsSL "$HUB/api/agent/hub_agent.py" -o "$DIR/hub_agent.py"

echo "[3/3] 登录（会打开浏览器）并配置本机的 agent……"
"$UV" run "$DIR/hub_agent.py" setup --hub "$HUB"
