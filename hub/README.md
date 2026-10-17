# 中枢部署（hub）

> **Windows 当前开发入口**：见 [Windows开发交接.md](../docs/Windows开发交接.md)。在 WSL Ubuntu 中使用本页命令；ComfyUI 原生跑在同一台 Windows 上，节点地址填 `http://host.docker.internal:8188`，不启用 frp profile。

中枢的全部服务都在 Docker 里运行，部署在中枢服务器（台式机）上，需要 Docker 和 Docker Compose v2。
本页是本仓库 `hub/` 的部署细节；**客户现场的完整部署（含员工电脑、GPU 机器的接入）照 [docs/部署清单.md](../docs/部署清单.md) 执行**。

| 服务 | 作用 | 默认端口 | 来源 |
|---|---|---|---|
| console-web | 控制台前端（nginx，并转发 /api，员工端接入接口也走这里） | **8088** | 自研，`console/frontend` |
| console-api | 控制台后端；含模型代理 `/v1`（员工模型调用经它进审计） | 不对外（经 console-web 转发 /api、/v1） | 自研，`console/backend` |
| hub-mcp | 中枢 MCP Server，员工端 agent 连这里 | **8200** | 自研，与 console-api 同一镜像 |
| Casdoor 4.20.0 | 身份（钉钉登录、组织架构） | 8000 | 开源镜像 |
| New API v0.13.2 | 模型网关（每个员工一个 key，按人计量） | 仅本机回环（管理后台） | 开源镜像 |
| hub-worker | GPU 调度：把生图任务派给 ComfyUI 节点、取回结果 | 不对外 | 自研，与 console-api 同一镜像 |
| frps | GPU 节点隧道服务端（profile `frp`）：GPU 机器不在同一网络时用它接入 | **7000**（唯一需对公网放行的端口） | 开源镜像 |
| mock-llm / mock-comfyui | 开发用模拟大模型 / 模拟 GPU 节点，仅 demo 环境 | 不对外 | 自研，与 console-api 同一镜像 |
| PostgreSQL 16 / Redis 7 | 共用数据库与缓存 | PostgreSQL 仅本机 25432 | 开源镜像 |
| RAGFlow v0.27.2 | 知识库检索（尚未接入） | 网页 8080 / API 9380 | 官方 compose，由 `ragflow/setup.sh` 拉取 |

PostgreSQL 里有三个库：`casdoor`、`newapi`，以及中枢自研服务用的 `hub`（岗位包、成员分配、审计日志）。

技能仓库 `skills/` 和知识库 `vault/` 留在宿主机上（方便用 Obsidian 和 git 维护），以只读方式挂载进 console-api 和 hub-mcp，改完立即生效，不用重建镜像。

## 硬件要求

不含 RAGFlow 时，2 核 4GB 就够。RAGFlow 官方最低要求 4 核 CPU、16GB 内存、50GB 磁盘，建议 32GB 内存。

## 首次部署

```bash
cd hub
make env          # 生成 .env，所有密码随机
vim .env          # 把 HUB_HOST、CASDOOR_ORIGIN 改成服务器局域网 IP；HUB_ORG / HUB_ORG_DISPLAY 改成企业名
make up           # 构建并启动全部服务
make bootstrap    # 初始化 Casdoor（企业组织、三个登录应用）和 New API（管理员、访问令牌），凭证写回 .env 并重启
```

然后：
1. 打开 Casdoor `http://<HUB_HOST>:8000`，用 `built-in/admin` 登录（密码是 `.env` 里的 `CASDOOR_ADMIN_PASSWORD`），给企业组织配置钉钉登录和组织同步，并把管理员账号设为组织管理员
2. 打开控制台 `http://<HUB_HOST>:8088`，用组织管理员登录
3. 在中枢服务器本机打开 New API 后台 `http://127.0.0.1:3001`（不对局域网开放，员工调用一律走中枢代理；管理员 `hubadmin`，密码见 `.env` 的 `NEWAPI_ADMIN_PASSWORD`）添加真实模型渠道，把 `.env` 的 `HUB_DEFAULT_MODEL` 设为渠道里的模型名，再执行 `make up`
4. 在 `.env` 的 `HUB_GPU_NODES` 里登记 GPU 机器上的 ComfyUI（见 [docs/gpu.md](../docs/gpu.md)），再执行 `make up`
5. 员工电脑上用接入器登录：`uv run agent/hub_agent.py login --hub http://<HUB_HOST>:8088`，见 [agent/README.md](../agent/README.md)

**开发或演示环境**用 `make bootstrap-demo` 代替 `make bootstrap`，会额外：
- 创建 9 个部门、18 名测试成员（含管理员 `admin`），密码写在 `.env` 的 `XINGHE_ADMIN_PASSWORD` / `XINGHE_USER_PASSWORD`
- 开启员工端账号密码登录（`HUB_AGENT_PASSWORD_LOGIN=true`）
- 启动模拟大模型 `mock-llm`（`.env` 写入 `COMPOSE_PROFILES=demo`），并在 New API 里建好渠道，`HUB_DEFAULT_MODEL=hub-mock`
- 没有登记 GPU 节点时，登记模拟节点 `mock-comfyui`

之后可以用 `console/backend/scripts/mcp_smoke.py` 或员工端接入器模拟员工使用。

知识库检索不配置 RAGFlow 时自动用本地关键词检索，可以晚点再接。接入时：

```bash
make ragflow-up           # 首次会拉约 10GB 镜像；Linux 上需要 vm.max_map_count=262144（setup.sh 会提示）
make ragflow-bootstrap    # 把 vault/ 知识库灌进 RAGFlow（建库、传文档、解析；API key 自动写回 .env）
vim .env                  # 把 RAGFLOW_ENDPOINT 填成 http://<HUB_HOST>:9380
make up                   # 重启自研服务生效
```

细节见 [docs/knowledge.md](../docs/knowledge.md)。

## 常用命令

| 命令 | 作用 |
|---|---|
| `make up` | 构建并启动全部服务；代码更新后再执行一次即可升级 |
| `make ps` / `make logs` | 查看状态 / 日志 |
| `make down` | 停止全部服务（数据保留在 `data/`） |
| `make bootstrap` / `make bootstrap-demo` | 初始化 Casdoor 与 New API（可重复执行） |
| `make db-hub` | 给早期创建的 PostgreSQL 数据目录补建 `hub` 库 |
| `make frp-token` | 打印 GPU 机器上 frpc 要填的隧道令牌 |
| `make frpc-config` | 按 `.env` 生成 GPU 机器的 frpc 配置（复制过去即可），见 [docs/frp-隧道接入.md](../docs/frp-隧道接入.md) |
| `make ragflow-up` / `make ragflow-down` | 启停 RAGFlow |

## 注意

- `.env` 里有全部密码和应用凭证，权限为 600，不要提交到 git（已在 .gitignore 中）
- `CASDOOR_ADMIN_PASSWORD` 和 `init-db.sh` 都只在数据目录为空、首次初始化时生效；之后改 `.env` 里的这些密码不会改动已有数据
- RAGFlow 首次启动后**不要再改** `RAGFLOW_*_PASSWORD`，否则它会连不上已初始化的数据
- 备份 `data/`（含生成的图片 `data/outputs/`）、`logs/`，以及仓库里的 `skills/`、`vault/`、`gpu-node/workflows/`
- 升级开源组件：改 `.env` 里的 `*_VERSION` 后执行 `make up`。RAGFlow 升级要先删掉 `ragflow/upstream/`，再执行 `make ragflow-up`
- 目前没有 HTTPS。员工在公司局域网内访问没有问题；需要外网访问时，前面加一层反向代理配证书，并在 `.env` 中相应修改地址
