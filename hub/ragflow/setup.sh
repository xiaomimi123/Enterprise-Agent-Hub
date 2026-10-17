#!/usr/bin/env bash
# 拉取指定版本的 RAGFlow 官方部署文件，并用 hub/.env 里的端口和密码覆盖官方默认值。
# 不改官方 compose 本身，升级时改 RAGFLOW_VERSION、删掉 upstream/ 重跑即可。
#
# 注意：RAGFlow 首次启动后再改密码，会导致它连不上自己已初始化的 MySQL / ES / MinIO。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../.env"
UPSTREAM="$HERE/upstream"

[ -f "$ENV_FILE" ] || { echo "缺少 hub/.env，先运行 make env"; exit 1; }
# 逐行读取 KEY=VALUE，不直接 source：.env 里有含空格和 | 的值（如 HUB_GPU_NODES），shell 会当成命令执行
while IFS='=' read -r key value; do
  case "$key" in ''|\#*|*[!A-Za-z0-9_]*) continue ;; esac
  export "$key=${value%$'
'}"
done < "$ENV_FILE"

if [ ! -d "$UPSTREAM" ]; then
  echo "拉取 RAGFlow $RAGFLOW_VERSION ..."
  git clone --depth 1 --branch "$RAGFLOW_VERSION" https://github.com/infiniflow/ragflow.git "$UPSTREAM"
fi

RF_ENV="$UPSTREAM/docker/.env"

# 把 RF_ENV 里的 KEY=... 整行替换为 KEY=VALUE（兼容 macOS / Linux）
set_kv() {
  KEY="$1" VALUE="$2" perl -pi -e 's/^\Q$ENV{KEY}\E=.*/$ENV{KEY}=$ENV{VALUE}/' "$RF_ENV"
  grep -q "^$1=" "$RF_ENV" || echo "$1=$2" >> "$RF_ENV"
}

set_kv RAGFLOW_IMAGE           "infiniflow/ragflow:$RAGFLOW_VERSION"
set_kv TZ                      "$TZ"
set_kv SVR_WEB_HTTP_PORT       "$RAGFLOW_WEB_PORT"
set_kv SVR_WEB_HTTPS_PORT      "8443"
set_kv SVR_HTTP_PORT           "$RAGFLOW_API_PORT"
set_kv ELASTIC_PASSWORD        "$RAGFLOW_ELASTIC_PASSWORD"
set_kv MYSQL_PASSWORD          "$RAGFLOW_MYSQL_PASSWORD"
set_kv MINIO_PASSWORD          "$RAGFLOW_MINIO_PASSWORD"
set_kv REDIS_PASSWORD          "$RAGFLOW_REDIS_PASSWORD"
set_kv ADMIN_DEFAULT_PASSWORD  "$RAGFLOW_ADMIN_PASSWORD"
# 嵌入模型：用官方自带的 TEI 服务（CPU 版，不占显卡，显卡留给 ComfyUI），Qwen3-Embedding 多语言、对中文友好
set_kv COMPOSE_PROFILES        "elasticsearch,cpu,metadata-mysql,tei-cpu"
set_kv TEI_MODEL               "${RAGFLOW_EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-0.6B}"

# Elasticsearch 在 Linux 上要求 vm.max_map_count >= 262144
if [ "$(uname)" = "Linux" ]; then
  current="$(sysctl -n vm.max_map_count 2>/dev/null || echo 0)"
  if [ "$current" -lt 262144 ]; then
    echo "⚠️  vm.max_map_count=$current，Elasticsearch 需要 >= 262144。请执行："
    echo "    sudo sysctl -w vm.max_map_count=262144"
    echo "    echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-ragflow.conf"
  fi
fi

echo "RAGFlow 配置完成：网页 http://${HUB_HOST}:${RAGFLOW_WEB_PORT}  API http://${HUB_HOST}:${RAGFLOW_API_PORT}"
