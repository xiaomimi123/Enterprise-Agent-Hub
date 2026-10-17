#!/usr/bin/env bash
# 从 .env.example 生成 .env，把所有 change_me_* 换成随机密码。已存在 .env 时不覆盖。
set -euo pipefail

HUB="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$HUB/.env" ] && { echo "hub/.env 已存在，未覆盖"; exit 0; }

cp "$HUB/.env.example" "$HUB/.env"
while grep -q 'change_me_[a-z]*' "$HUB/.env"; do
  placeholder="$(grep -o 'change_me_[a-z]*' "$HUB/.env" | head -1)"
  PH="$placeholder" PW="$(openssl rand -hex 16)" perl -pi -e 's/\Q$ENV{PH}\E/$ENV{PW}/' "$HUB/.env"
done
chmod 600 "$HUB/.env"

# frp 隧道令牌：GPU 机器上的 frpc 要用同一个（make frp-token 可随时打印）
if [ ! -f "$HUB/frp/token" ]; then
  openssl rand -hex 24 > "$HUB/frp/token"
  chmod 600 "$HUB/frp/token"
fi

echo "已生成 hub/.env（随机密码）。请手动改 HUB_HOST 和 CASDOOR_ORIGIN 为中枢服务器的局域网地址。"
