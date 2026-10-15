# 中枢部署（hub）

部署在中枢服务器（台式机）上，需要 Docker 和 Docker Compose v2。

| 服务 | 作用 | 默认端口 | 部署方式 |
|---|---|---|---|
| Casdoor 4.20.0 | 身份（钉钉登录、组织架构） | 8000 | 本目录 `docker-compose.yml` |
| New API v0.13.2 | 模型网关（按人发 key、计量） | 3000 | 本目录 `docker-compose.yml` |
| PostgreSQL 16 / Redis 7 | Casdoor 和 New API 共用，不对宿主机开放端口 | — | 本目录 `docker-compose.yml` |
| RAGFlow v0.27.2 | 部门知识库 | 网页 8080 / API 9380 | 官方 compose，由 `ragflow/setup.sh` 拉取 |

RAGFlow 自带 Elasticsearch、MySQL、MinIO、Redis，组件多且官方 compose 更新频繁，所以不合并进本目录的 compose，只用脚本覆盖端口和密码。

## 硬件要求

RAGFlow 官方最低要求：4 核 CPU、16GB 内存、50GB 磁盘，建议 32GB 内存。Casdoor 和 New API 很轻。

## 启动

```bash
cd hub
make env          # 生成 .env，所有密码随机
vim .env          # 把 HUB_HOST、CASDOOR_ORIGIN 改成服务器局域网 IP
make up           # Casdoor + New API
make ragflow-up   # RAGFlow（首次会拉约 10GB 镜像）
```

Linux 上首次启动 RAGFlow 前，需要设置 `vm.max_map_count=262144`（`setup.sh` 会检查并提示命令）。

## 启动后的初始化

- **Casdoor**：`http://<HUB_HOST>:8000`，账号 `built-in/admin`，密码是 `.env` 里的 `CASDOOR_ADMIN_PASSWORD`（只在首次启动时生效）
- **New API**：`http://<HUB_HOST>:3000`，首次访问时创建管理员
- **RAGFlow**：`http://<HUB_HOST>:8080`，注册第一个账号；管理员密码见 `.env` 的 `RAGFLOW_ADMIN_PASSWORD`

## 常用命令

| 命令 | 作用 |
|---|---|
| `make ps` / `make ragflow-ps` | 查看状态 |
| `make logs` | 查看 Casdoor / New API 日志 |
| `make all-up` / `make all-down` | 全部启动 / 停止 |

## 注意

- `.env` 里有全部密码，权限为 600，不要提交到 git（已在 .gitignore 中）
- RAGFlow 首次启动后**不要再改** `RAGFLOW_*_PASSWORD`，否则它会连不上已初始化的数据
- `init-db.sh` 只在 PostgreSQL 数据目录为空时执行一次。改 `CASDOOR_DB_PASSWORD` / `NEWAPI_DB_PASSWORD` 不会更新已有数据库
- 数据在 `data/`，日志在 `logs/`，备份时备份这两个目录和 RAGFlow 的 Docker 卷
- 升级：改 `.env` 里的 `*_VERSION`。RAGFlow 升级要先删掉 `ragflow/upstream/`，再执行 `make ragflow-up`
