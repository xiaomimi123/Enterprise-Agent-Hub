# 中枢 MCP Server

## 目的

员工的 agent（以及经授权的外部智能体）通过 MCP 连到中枢，使用技能和企业知识库。MCP Server 是「权限在中枢强制执行」的落点：每次调用都核对员工身份和岗位包，并写入审计日志。

代码：`console/backend/app/mcp_server.py`（和控制台后端在同一个 Python 项目里，共用数据库、权限和内容模块）。

部署时作为 compose 里的 `hub-mcp` 服务运行（与控制台后端同一镜像），地址 `http://<中枢>:8200/mcp`（Streamable HTTP）。本地开发也可以直接运行：

```bash
cd console/backend
uv run uvicorn app.mcp_server:app --reload --port 8200
```

## 工具

| 工具 | 作用 | 权限要求 |
|---|---|---|
| `whoami` | 当前员工、部门、入口、岗位包、可用技能和知识库 | 有效令牌 |
| `list_skills` | 岗位包内的技能列表 | 官方 agent，岗位包含 `skill.read` |
| `read_skill(skill_id)` | 读取 SKILL.md 全文 | 同上，且技能在岗位包内 |
| `search_knowledge(query, knowledge_base?)` | 检索知识库；指定库名则只查该库 | 岗位包含 `kb.search`；外部智能体另需岗位包「外部只读」且知识库开放给外部 |
| `generate_cover(title, description?)` | 派发到 GPU 节点生成 3 版封面，最多等 90 秒，见 [gpu.md](gpu.md) | 官方 agent，岗位包含 `image.cover` |
| `generate_image(prompt, aspect?, count?)` | 文生图（Z-Image-Turbo） | 官方 agent，岗位包含 `image.generate` |
| `generate_video(prompt, aspect?, seconds?)` | 文生视频（MiniMax-H3，带声音） | 官方 agent，岗位包含 `video.generate` |
| `generate_video_from_image(image_url, prompt, seconds?)` | 图生视频，参考图只收中枢签发的链接 | 同上 |
| `list_apps` | 当前岗位包能在本机打开的应用 | 官方 agent，岗位包 `apps` 列表 |
| `open_app(app_id)` | 返回带签名下载链接和 SHA-256 的启动凭证；本机接入器的 MCP 桥拦截后下载、校验、启动并回报网址，见 [app-launcher](superpowers/specs/2026-10-19-app-launcher-design.md) | 官方 agent，岗位包 `apps` 含该应用 |
| `report_work(title, kind, status, progress, link, note, item_id)` | 上报工作成果 / 进度 | 所有人；只能改自己的条目 |
| `my_work(days)` | 查看自己上报的成果 | 只看自己 |
| `team_report(days, person)` | 团队成果与进度汇总（日报素材） | 老板 / 管理员看全公司，部门主管只看自己部门，其他人和外部入口不可用 |
| `get_task(task_id)`（旧名 `get_cover_task`） | 查询生成任务进度和结果链接 | 只能查自己的任务 |

生成类工具每人最多同时 3 个未完成任务（`HUB_GPU_MAX_PENDING_PER_USER`）。

被拒绝时返回明确原因（例如「岗位包『小红书运营』没有『财务制度与报表』的检索权限」），并记一条「拒绝」审计。

## 关键设计

**身份 = Casdoor 令牌。** 请求头 `Authorization: Bearer <JWT>`。MCP Server 用 Casdoor 的 JWKS 校验签名和有效期，并要求令牌属于本企业组织。

**入口由签发应用决定，而不是请求头。** Casdoor 里有两个应用：
- `hub-agent`：员工端官方 agent → 入口「官方 agent」，享有岗位包的全部能力
- `hub-external`：ChatGPT、Claude 等外部智能体 → 入口「外部智能体」，只能检索开放给外部的知识库，不能读技能

控制台应用 `hub-console` 签发的令牌不被 MCP 接受。请求头是客户端可以随意填写的，所以只用来传递任务描述，不用来判断权限。

**权限判断集中在 `policy.py`。** 岗位包和成员分配从数据库实时读取，控制台一改，下一次 MCP 调用立即生效。提示词里怎么写都绕不过去：注入「忽略限制」的请求和普通越权请求一样被拒绝。

**审计。** 每次工具调用写一条 `audit_events`。同一任务共用 `trace_id`：优先取请求头 `X-Hub-Trace-Id`，否则用 MCP 会话 ID。请求头 `X-Hub-Task`（URL 编码）可以带上任务描述，显示在控制台审计日志中。

**内容。**
- 技能：`skills/<部门>/<技能 id>/SKILL.md`
- 知识库：`vault/<知识库名>/*.md`（Obsidian vault）是内容来源。配置了 RAGFlow（`RAGFLOW_ENDPOINT` + `RAGFLOW_API_KEY`）时，`content.search()` 走 RAGFlow 向量 + 关键词混合检索；未配置或 RAGFlow 出错时回退到本地字符二元组关键词检索，返回结构相同。详见下文「RAGFlow 知识库」

## RAGFlow 知识库

一个知识库 = RAGFlow 里的一个数据集（`hub-<kb_id>`），嵌入模型是 RAGFlow 自带 TEI 服务的 Qwen3-Embedding-0.6B（CPU 运行，不占显卡）。

- **权限仍在中枢**：先按岗位包算出 `allowed_kbs`，只把这些库的数据集 ID 传给 RAGFlow；没同步到 RAGFlow 的库直接跳过（绝不扩大范围）；返回的命中若不属于本次允许的库会被丢弃
- **同步**：`make kb-sync`（容器里 `scripts/ragflow_sync.py --wait`）把 vault 推到 RAGFlow，幂等：按「文件名 + 字节数」判断，改了的先删后传，本地删掉的同步删除。改了 vault 记得重新同步
- **回退**：RAGFlow 不可达、超时、返回错误或非 JSON 时，记 warning 并回退本地检索，MCP 调用不会因此失败
- **初始化**：RAGFlow 启动后执行一次 `make ragflow-bootstrap`，注册管理员 `admin@hub.local`（密码是 `.env` 的 `RAGFLOW_ADMIN_PASSWORD`）、创建 API Key 并写入 `.env`
- **Windows / Docker Desktop**：官方 ES 端口 1200 常落在 Hyper-V 保留端口段，已改 19200；TEI 官方默认批量 token 数会让预热内存冲到 20GB+ 被 OOM 杀掉，`hub/ragflow/docker-compose.override.yml` 把它降到 2048（稳定在约 3GB）

## 数据库

PostgreSQL 的 `hub` 库（`hub/docker-compose.yml` 里的同一个 PostgreSQL），由控制台后端或 MCP Server 启动时自动建表：

| 表 | 内容 |
|---|---|
| `role_packs` | 岗位包定义；首次启动时写入演示岗位包作为初始数据 |
| `role_assignments` | 成员 → 岗位包；没有记录的成员按部门默认岗位包 |
| `audit_events` | 审计事件，一步一行 |

## 本地验证

```bash
cd hub && make up && make bootstrap-demo                 # 启动全部服务，创建应用和测试成员
cd ../console/backend && uv run python scripts/mcp_smoke.py   # 模拟运营、财务员工和外部智能体调用
```

冒烟脚本覆盖：运营员工正常读技能和查知识、越权查财务被拒、提示词注入被拒、财务员工正常查报销制度、外部智能体只能读开放的知识库。跑完后，控制台审计日志里能看到这几条链路。

## 取舍与后续

- 开发环境的 agent 应用开启了 password 授权，方便脚本取令牌；生产环境应改为授权码或设备码流程，由员工端 agent 引导员工扫码登录
- 控制台「知识库」页的文档列表和索引状态已读 RAGFlow（未同步的库读本地 vault）；检索结果的 `section`（所属章节）暂为空，RAGFlow 按分块返回，不带章节标题
- 已容器化：与控制台后端共用 `hub-backend` 镜像，见 `hub/docker-compose.yml`

## 对话模型上游（控制台「模型」页）

管理员不必再打开 New API 后台：在「模型」页的「对话模型」分区添加上游（名称、`https://…/v1` 地址、密钥），点「测试连接」拉取模型清单，勾选要开放的模型后保存。

- 上游以 New API 渠道为唯一真相，密钥只存在 New API；中枢通过管理令牌读写渠道，页面只显示后四位，编辑时密钥留空表示不改。
- 开放的模型会成为岗位包「可用模型」的候选；停用或删除上游后，员工的 key 在下次领取配置时不再包含这些模型。
- 所有增删改与测试都写审计（不含密钥）；接口 `/api/models/upstreams*` 仅管理员可用。

## 模型价格（控制台「模型」页 → 模型价格）

员工的用量费用、月度额度、岗位包的成本统计，都按模型网关（New API）里的价格计算。管理员在「模型价格」里按**美元 / 百万 token**填每个开放模型的输入价和输出价（输出价留空则与输入价相同），保存后立即生效，不用重启。

- 实现：写 New API 的 `ModelRatio`（输入倍率 = 输入价 ÷ 2，倍率 1 = 每百万 $2）和 `CompletionRatio`（输出倍率 = 输出价 ÷ 输入价）；只改所选模型，其他模型的价格原样保留。「恢复默认」会清除该模型的自定义价格。
- **没设置价格的模型**，New API 按默认倍率 37.5（每百万 token $75）计费，费用严重虚高：例如 CodeBuddy 每次请求带约 2.5 万 token 上下文，单次就扣约 $2，岗位包的月度额度几小时就被「花光」，之后请求被网关以 403 拒绝。页面会提示「N 个模型还没设置价格」。
- 已对真实 New API 验证：同一个 35 输入 + 5 输出 token 的请求，没设价格时扣 1500 额度，设成 $0.14 / $0.28 后只扣 3，立即生效。
- 每次设置 / 清除都写审计（`model.pricing.set` / `model.pricing.clear`）。
