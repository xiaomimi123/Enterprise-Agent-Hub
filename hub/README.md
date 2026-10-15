# 中枢部署（hub）

中枢的全部服务都在 Docker 里运行，部署在中枢服务器（台式机）上，需要 Docker 和 Docker Compose v2。

| 服务 | 作用 | 默认端口 | 来源 |
|---|---|---|---|
| console-web | 控制台前端（nginx，并转发 /api） | **8088** | 自研，`console/frontend` |
| console-api | 控制台后端 | 不对外 | 自研，`console/backend` |
| hub-mcp | 中枢 MCP Server，员工端 agent 连这里 | **8200** | 自研，与 console-api 同一镜像 |
| Casdoor 4.20.0 | 身份（钉钉登录、组织架构） | 8000 | 开源镜像 |
| New API v0.13.2 | 模型网关（按人发 key、计量） | 3000 | 开源镜像 |
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
make bootstrap    # 在 Casdoor 里创建企业组织和三个登录应用，凭证自动写回 .env，并重启自研服务
```

然后：
1. 打开 Casdoor `http://<HUB_HOST>:8000`，用 `built-in/admin` 登录（密码是 `.env` 里的 `CASDOOR_ADMIN_PASSWORD`），给企业组织配置钉钉登录和组织同步，并把管理员账号设为组织管理员
2. 打开控制台 `http://<HUB_HOST>:8088`，用组织管理员登录
3. 员工端 agent 连接 `http://<HUB_HOST>:8200/mcp`

**开发或演示环境**用 `make bootstrap-demo` 代替 `make bootstrap`：会额外创建 9 个部门、18 名测试成员（含管理员 `admin`），密码写在 `.env` 的 `XINGHE_ADMIN_PASSWORD` / `XINGHE_USER_PASSWORD`；并给 agent 应用开启 password 授权，方便用 `console/backend/scripts/mcp_smoke.py` 模拟员工调用。

知识库检索接入 RAGFlow 之前，不需要启动 RAGFlow。需要时：

```bash
make ragflow-up   # 首次会拉约 10GB 镜像；Linux 上需要 vm.max_map_count=262144（setup.sh 会提示）
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `make up` | 构建并启动全部服务；代码更新后再执行一次即可升级 |
| `make ps` / `make logs` | 查看状态 / 日志 |
| `make down` | 停止全部服务（数据保留在 `data/`） |
| `make bootstrap` / `make bootstrap-demo` | 初始化 Casdoor（可重复执行） |
| `make db-hub` | 给早期创建的 PostgreSQL 数据目录补建 `hub` 库 |
| `make ragflow-up` / `make ragflow-down` | 启停 RAGFlow |

## 注意

- `.env` 里有全部密码和应用凭证，权限为 600，不要提交到 git（已在 .gitignore 中）
- `CASDOOR_ADMIN_PASSWORD` 和 `init-db.sh` 都只在数据目录为空、首次初始化时生效；之后改 `.env` 里的这些密码不会改动已有数据
- RAGFlow 首次启动后**不要再改** `RAGFLOW_*_PASSWORD`，否则它会连不上已初始化的数据
- 备份 `data/`、`logs/`，以及仓库里的 `skills/`、`vault/`
- 升级开源组件：改 `.env` 里的 `*_VERSION` 后执行 `make up`。RAGFlow 升级要先删掉 `ragflow/upstream/`，再执行 `make ragflow-up`
- 目前没有 HTTPS。员工在公司局域网内访问没有问题；需要外网访问时，前面加一层反向代理配证书，并在 `.env` 中相应修改地址
