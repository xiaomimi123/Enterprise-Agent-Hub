#!/bin/sh
# 企业智能体中枢 · macOS / Linux 一键接入。由中枢在 /api/agent/install.sh 提供，__HUB_URL__ 会被替换成中枢地址。
# 用法：curl -fsSL http://<中枢>:8088/api/agent/install.sh | sh
# 步骤：没有 uv 就安装 → （询问后）安装 Node.js 和 CodeBuddy CLI → 下载接入器 → 浏览器登录 → 自动配置 WorkBuddy / CodeBuddy CLI / Cursor / Claude 桌面版
# 可选工具绝不静默安装。环境变量：
#   HUB_INSTALL_TOOLS=yes  不询问，直接安装 Node.js / CodeBuddy CLI
#   HUB_INSTALL_TOOLS=no   一律不装（也不询问）
#   HUB_INSTALL_DRYRUN=1   只打印会安装什么
# 没有可交互的终端时（例如由 agent 执行本脚本）不会安装，只打印安装命令。
set -e
HUB='__HUB_URL__'
DIR="$HOME/.hub-agent"
ORIG_PATH="$PATH"
# 追加而不是前置：前置会让 ~/.local/bin 里别的工具链留下的 node（可能是 alpha 版）压过系统里正常的 Node
export PATH="$PATH:$HOME/.local/bin"

confirm() {  # confirm "<名称>"：默认否；脚本是管道输入，所以从 /dev/tty 读回答
  case "$HUB_INSTALL_TOOLS" in yes) return 0 ;; no) return 1 ;; esac
  # 脚本是管道输入（curl | sh），stdin 不是终端，所以回答要从 /dev/tty 读；
  # 但 agent / IDE 拉起的子进程也继承了控制终端，/dev/tty 能打开不代表有人在看，
  # 所以还要求标准输出是终端（agent 会捕获输出），并排除常见的 agent / CI 环境变量
  if [ -t 1 ] && [ -z "$CI" ] && [ -z "$CLAUDECODE" ] && [ -z "$CODEBUDDY_CODE" ] && ! env | grep -q '^WORKBUDDY_' && ( exec < /dev/tty ) 2>/dev/null; then
    printf "      现在安装 %s 吗？[y/N] " "$1" > /dev/tty
    read -r answer < /dev/tty || answer=""
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
  fi
  echo "      （没有可交互的终端，已跳过。要自动安装，重新运行：HUB_INSTALL_TOOLS=yes curl -fsSL $HUB/api/agent/install.sh | sh ）"
  return 1
}
run() {  # run "<说明>" <命令…>
  desc="$1"; shift
  if [ "$HUB_INSTALL_DRYRUN" = "1" ]; then echo "      [dry-run] 将执行：$desc"; return 0; fi
  echo "      执行：$desc"
  "$@"
}

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "[1/4] 安装 uv（Python 运行器）……"
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo "[1/4] uv 已安装"
fi
UV=$(command -v uv || echo "$HOME/.local/bin/uv")

echo "[2/4] 检查可选工具……"
if command -v node >/dev/null 2>&1; then
  echo "      Node.js：已安装（$(node -v 2>/dev/null)）"
  case "$(node -v 2>/dev/null)" in *-*) echo "      注意：这是预发布版 Node（alpha / rc），npm 可能报版本不兼容警告；警告不一定表示失败，装完会再验证。" ;; esac
else
  echo "      Node.js：未安装（打开公司应用，如小红书工作台，需要它）"
  if command -v brew >/dev/null 2>&1; then
    if confirm "Node.js（brew install node）"; then run "brew install node" brew install node; fi
  else
    echo "      请到 https://nodejs.org 下载 LTS 安装包，或用系统的包管理器安装（例如 sudo apt install nodejs npm），装好后重新运行本命令。"
  fi
fi
if command -v codebuddy >/dev/null 2>&1; then
  echo "      CodeBuddy CLI：已安装"
else
  echo "      CodeBuddy CLI：未安装（只有工作台里的浏览器自动化需要；只用 WorkBuddy 的话可以不装）"
  if command -v npm >/dev/null 2>&1; then
    if confirm "CodeBuddy CLI（npm install -g，装到 ~/.local，不需要 sudo）"; then
      run "npm install -g --prefix ~/.local @tencent-ai/codebuddy-code" npm install -g --prefix "$HOME/.local" @tencent-ai/codebuddy-code
      if [ "$HUB_INSTALL_DRYRUN" != "1" ]; then
        if "$HOME/.local/bin/codebuddy" --version >/dev/null 2>&1; then echo "      CodeBuddy CLI 已装好（$("$HOME/.local/bin/codebuddy" --version 2>/dev/null)）"; else echo "      CodeBuddy CLI 没有装成功，可以忽略（只用 WorkBuddy 不需要），或稍后手动：npm install -g @tencent-ai/codebuddy-code"; fi
      fi
      case ":$ORIG_PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "      请把 ~/.local/bin 加进 PATH，重开终端后才能直接用 codebuddy：echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;; esac
    else
      echo "      自己安装：npm install -g @tencent-ai/codebuddy-code"
    fi
  else
    echo "      先安装 Node.js，再执行：npm install -g @tencent-ai/codebuddy-code"
  fi
fi

echo "[3/4] 下载接入器……"
mkdir -p "$DIR"
curl -fsSL "$HUB/api/agent/hub_agent.py" -o "$DIR/hub_agent.py"

if [ "$HUB_INSTALL_DRYRUN" = "1" ]; then echo "[4/4] [dry-run] 到此为止，不登录。"; exit 0; fi
echo "[4/4] 登录（会打开浏览器）并配置本机的 agent……"
echo "      提示：首次登录需要先把初始密码改成自己的新密码；浏览器没有自动打开时，把输出里的登录链接复制到浏览器。"
PYTHONUNBUFFERED=1 "$UV" run "$DIR/hub_agent.py" setup --hub "$HUB"
if command -v codebuddy >/dev/null 2>&1 || [ -x "$HOME/.local/bin/codebuddy" ]; then
  echo ""
  echo "CodeBuddy CLI 提示：浏览器自动化还需要它自己的账号登录一次：终端运行 codebuddy，输入 /login。"
fi
