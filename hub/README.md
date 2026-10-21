# 中枢部署（hub）

中枢的全部服务都在 Docker 里运行，部署在中枢服务器（台式机）上，需要 Docker 和 Docker Compose v2。

| 服务 | 作用 | 默认端口 | 来源 |
|---|---|---|---|
| console-web | 控制台前端（nginx，并转发 /api，员工端接入接口也走这里） | **8088** | 自研，`console/frontend` |
| console-api | 控制台后端 | 不对外 | 自研，`console/backend` |
| hub-mcp | 中枢 MCP Server，员工端 agent 连这里 | **8200** | 自研，与 console-api 同一镜像 |
| Casdoor 4.20.0 | 身份（自建账号、组织架构） | 8000 | 开源镜像 |
| New API v0.13.2 | 模型网关（每个员工一个 key，按人计量） | 3000 | 开源镜像 |
| hub-worker | GPU 调度：把生图任务派给 ComfyUI 节点、取回结果 | 不对外 | 自研，与 console-api 同一镜像 |
| mock-llm / mock-comfyui | 开发用模拟大模型 / 模拟 GPU 节点，仅 demo 环境 | 不对外 | 自研，与 console-api 同一镜像 |
| PostgreSQL 16 / Redis 7 | 共用数据库与缓存 | PostgreSQL 仅本机 25432 | 开源镜像 |
| RAGFlow v0.27.2 | 知识库检索（已接入 MCP 的 search_knowledge） | 网页 8080 / API 9380 | 官方 compose，由 `ragflow/setup.sh` 拉取 |

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

**局域网开放（Windows 防火墙，需管理员 PowerShell 执行）：**
```powershell
# 员工电脑要访问：控制台与接入接口 8088、MCP 8200、Casdoor 登录 8000、New API 模型网关 3000；只对局域网（专用网络）开放
New-NetFirewallRule -DisplayName "Hub (console, MCP, login, model gateway)" -Direction Inbound -Protocol TCP -LocalPort 8088,8200,8000,3000 -Action Allow -Profile Private
```
ComfyUI 没有鉴权，不要对局域网开放：在 ComfyUI Desktop 的设置里把监听地址（Server Config → Listen / Host）改成 `127.0.0.1` 后重启 ComfyUI。中枢容器经 `host.docker.internal` 访问宿主机的 127.0.0.1 不受影响（已实测）。**不要**用防火墙「阻止」规则拦 8188：容器访问宿主机在 Windows 看来也是入站连接，阻止规则会连中枢自己一起拦掉。
同时确认网卡的网络类型是「专用」。RAGFlow（8080/9380）只有中枢自己和管理员访问，不必放行。

**启用 RAGFlow 知识库：**
```bash
make ragflow-up          # 拉取官方部署文件并启动（镜像约 13GB，首次较慢；嵌入服务 TEI 会再下载一次模型）
make ragflow-bootstrap   # 建管理员和 API Key，写回 .env（RAGFLOW_ENDPOINT、RAGFLOW_API_KEY）
docker compose up -d     # 让 console-api、hub-mcp 读到新配置
make kb-sync             # 把 vault 里的知识库同步到 RAGFlow
```
内存建议 ≥ 32GB（Docker Desktop 虚拟机分到 ≥ 16GB）。不启用时 `search_knowledge` 自动用本地关键词检索。

**Windows（Docker Desktop）注意：**
- 没有 `make` 时，把 Makefile 里的命令直接用 `docker compose` 执行：`docker compose up -d --build`；初始化为 `docker compose run --rm --no-deps -v <绝对路径>/.env:/hub.env console-api python scripts/casdoor_bootstrap.py --env-file /hub.env --casdoor-url http://casdoor:8000 [--demo]`，再执行 `newapi_bootstrap.py ... --newapi-url http://new-api:3000 [--demo]`，最后 `docker compose up -d`（在 Git Bash 里加 `MSYS_NO_PATHCONV=1`）
- 挂载进容器的 `.sh` 必须是 LF 换行，仓库的 `.gitattributes` 已固定；如果 PostgreSQL 日志出现 `bad interpreter: /bin/bash^M`，说明是旧的 CRLF 检出，转成 LF 后 `docker compose down -v` 重建
- 中枢和 ComfyUI 同机时 `HUB_GPU_NODES` 填 `http://host.docker.internal:8188`，见 [docs/gpu.md](../docs/gpu.md)

然后：
1. 打开 Casdoor `http://<HUB_HOST>:8000`，用 `built-in/admin` 登录（密码是 `.env` 里的 `CASDOOR_ADMIN_PASSWORD`），并把管理员账号设为组织管理员；成员账号之后在控制台「成员与组织」页创建或批量导入，不需要钉钉
2. 打开控制台 `http://<HUB_HOST>:8088`，用组织管理员登录
3. 在控制台「模型」页添加真实对话模型上游并开放模型（也可到 New API 后台 `http://<HUB_HOST>:3000` 手动建渠道，管理员 `hubadmin`，密码见 `.env` 的 `NEWAPI_ADMIN_PASSWORD`），把 `.env` 的 `HUB_DEFAULT_MODEL` 设为开放的模型名，再执行 `make up`；需要第三方出图时在同一页添加出图 API 并切换通道，见 [docs/gpu.md](../docs/gpu.md)
4. 在 `.env` 的 `HUB_GPU_NODES` 里登记 GPU 机器上的 ComfyUI（见 [docs/gpu.md](../docs/gpu.md)），再执行 `make up`
5. 员工电脑上用接入器登录：`uv run agent/hub_agent.py login --hub http://<HUB_HOST>:8088`，见 [agent/README.md](../agent/README.md)

**开发或演示环境**用 `make bootstrap-demo` 代替 `make bootstrap`，会额外：
- 创建 9 个部门、18 名测试成员（含管理员 `admin`），密码写在 `.env` 的 `XINGHE_ADMIN_PASSWORD` / `XINGHE_USER_PASSWORD`
- 开启员工端账号密码登录（`HUB_AGENT_PASSWORD_LOGIN=true`）
- 启动模拟大模型 `mock-llm`（`.env` 写入 `COMPOSE_PROFILES=demo`），并在 New API 里建好渠道，`HUB_DEFAULT_MODEL=hub-mock`
- 没有登记 GPU 节点时，登记模拟节点 `mock-comfyui`

之后可以用 `console/backend/scripts/mcp_smoke.py` 或员工端接入器模拟员工使用。

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
| `make bootstrap` / `make bootstrap-demo` | 初始化 Casdoor 与 New API（可重复执行） |
| `make db-hub` | 给早期创建的 PostgreSQL 数据目录补建 `hub` 库 |
| `make ragflow-up` / `make ragflow-down` | 启停 RAGFlow |

## 注意

- `.env` 里有全部密码和应用凭证，权限为 600，不要提交到 git（已在 .gitignore 中）
- `CASDOOR_ADMIN_PASSWORD` 和 `init-db.sh` 都只在数据目录为空、首次初始化时生效；之后改 `.env` 里的这些密码不会改动已有数据
- RAGFlow 首次启动后**不要再改** `RAGFLOW_*_PASSWORD`，否则它会连不上已初始化的数据
- 备份 `data/`（含生成的图片 `data/outputs/`）、`logs/`，以及仓库里的 `skills/`、`vault/`、`gpu-node/workflows/`
- 升级开源组件：改 `.env` 里的 `*_VERSION` 后执行 `make up`。RAGFlow 升级要先删掉 `ragflow/upstream/`，再执行 `make ragflow-up`
- 目前没有 HTTPS。员工在公司局域网内访问没有问题；需要外网访问时，前面加一层反向代理配证书，并在 `.env` 中相应修改地址

## 身份与登录页

身份直接使用 Casdoor 自建账号（不接钉钉）：管理员在 Casdoor 里建组织、部门、成员。登录页不引用任何境外资源：`docker-compose.yml` 里 Casdoor 启动时把前端写死的 `cdn.casbin.org` 改指向本服务的 `/static-cdn`（文件在 `hub/casdoor-static/`：徽标、图标、manifest），并设置 `staticBaseUrl`；应用与组织的徽标由 `console/backend/scripts/casdoor_brand.py` 写入。升级 Casdoor 版本后重新 `make up` 即可，替换是按字符串做的，不依赖具体版本。

### 成员账号管理

控制台「成员与组织」页（管理员）：

- **新建**：填用户名、姓名、部门，初始密码可自填或留空随机生成（至少 8 位，含字母和数字）。初始密码只在创建后的弹窗里显示一次；员工首次登录 Casdoor 会强制修改密码，改完才能换到令牌。
- **批量导入**：上传 CSV，表头 `username,display_name,dept,title,phone,email,password`（dept 填部门名称，password 留空则随机生成，一次最多 500 人）；逐行创建，失败的行给出原因，成功行的初始密码在结果里显示一次，可导出。
- **重置密码**、**编辑**（姓名、部门、职位、手机、邮箱）、**停用 / 启用**、**删除**。管理员账号和自己的账号不能停用或删除。
- **停用即失效**：Casdoor 立即禁止登录；该员工在模型网关的全部 key 被回收；已签发的令牌（有效期 24 小时，刷新令牌 7 天）由中枢在 30 秒内拒绝（每次请求按账号状态校验，查询结果缓存 30 秒；身份服务暂时不可用时放行，不拖垮其他人）。重新启用后，员工下次领取配置会自动新建 key。
- 登录失败 5 次锁定 15 分钟（Casdoor 应用默认）；密码规则「至少 8 位」由 `casdoor_bootstrap.py` 写入组织。
- 所有操作写审计（密码不入审计）。生产环境员工端只能走浏览器登录（授权码 + PKCE），账号密码直换令牌仅在 `bootstrap-demo` 时开启。
