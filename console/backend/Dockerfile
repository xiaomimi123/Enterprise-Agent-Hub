# 中枢后端镜像：控制台 API 与 MCP Server 共用，启动命令不同
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 TZ=Asia/Shanghai

WORKDIR /app
# 先装依赖，利用镜像层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY scripts ./scripts

# 技能仓库与知识库从宿主机挂载
ENV HUB_SKILLS_DIR=/data/skills HUB_VAULT_DIR=/data/vault
EXPOSE 8100 8200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
