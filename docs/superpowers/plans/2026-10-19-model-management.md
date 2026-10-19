# 控制台「模型」页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员在控制台「模型」页接入对话模型上游和第三方出图 API，并在本机 GPU / 第三方 API 之间手动切换出图通道。

**Architecture:** 对话模型上游以 New API 渠道为唯一真相（`NewApi` 客户端增加渠道读写）；出图 API 的配置存中枢数据库新表 `hub_settings`（密钥用 HUB_FILE_SECRET 派生的 Fernet 加密）；API 出图复用 `gpu_tasks` 队列与 worker，workflow 记为 `api-image`，worker 新增 API 分支（提交→存第三方任务号→轮询→下载到 outputs）。前端新增「模型」页（React + antd，沿用现有页面组件）。

**Tech Stack:** FastAPI、psycopg、httpx、cryptography（已随 pyjwt[crypto] 安装）、React 19 + Ant Design 6、pytest。

**Spec:** docs/superpowers/specs/2026-10-19-model-management-design.md

## Global Constraints

- 密钥不得出现在任何接口响应、日志、审计详情、错误信息里；页面只显示后四位（`mask_secret`）。
- 所有 `/api/...` 控制台接口已由 `api` 路由的 `auth.current_user` 依赖限定为管理员，新接口挂在同一个 `api` 路由下。
- 每次增删改上游 / 出图 API、切换通道、测试，写一条审计（`db.add_audit`，kind「配置」，不含密钥）。
- `image.route` 默认 `"gpu"`；切到 `"api"` 前必须存在一个已启用的出图 API，否则 400。
- 切换通道只影响之后提交的任务。API 任务不占 GPU：不计入 `gpu_seconds_this_month`，不被 GPU 节点领取。
- 每人最多同时未完成任务（`gpu_max_pending_per_user`）对 API 任务同样生效。
- 测试：后端 `console/backend/.venv/Scripts/python -m pytest -q`；前端 `npx tsc -b`。提交信息以中文 `feat:` / `test:` / `docs:` 开头，结尾加 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`；永远不要 add `windows节点搭建任务书.md`。

## Review Focus

1. 密钥泄漏：列表 / 探测 / 保存失败的响应与审计里不含完整密钥（Task 1、2、3 各有测试）。
2. 编辑时密钥留空 = 不改（Task 2、3）。
3. 出图 API 返回失败、超时、返回空图：任务变 `failed` 并写审计，不卡在 `running`（Task 4）。
4. worker 重启：已存第三方任务号的任务恢复轮询，不重复提交（Task 4）。
5. 切换通道后，已在排队 / 运行的旧任务不受影响（Task 4）。

---

### Task 1: 密钥加密与设置存储

**Files:**
- Create: `console/backend/app/secretbox.py`, `console/backend/app/settings_store.py`
- Modify: `console/backend/app/db.py`（`SCHEMA` 加 `hub_settings` 表）
- Test: `console/backend/tests/test_secretbox.py`

**Interfaces:**
- Produces: `secretbox.encrypt(plain: str) -> str`、`secretbox.decrypt(token: str) -> str`、`secretbox.mask_secret(plain: str) -> str`（`"sk-abcdef1234"` → `"••••1234"`，长度≤4 全遮）。`settings_store.get(key: str, default=None)`、`settings_store.put(key: str, value) -> None`（值为 JSON 可序列化对象；表 `hub_settings(key TEXT PRIMARY KEY, value JSONB, updated_at TIMESTAMPTZ)`）。没有 `HUB_FILE_SECRET` 时 `encrypt` 抛 `RuntimeError("未配置 HUB_FILE_SECRET")`。

- [ ] **Step 1: 写失败测试** `test_secretbox.py`：加解密往返（中文也行）；`encrypt` 输出不含明文；`mask_secret("sk-abcdef1234") == "••••1234"`、`mask_secret("abc") == "••••"`；换了 `file_secret` 后 `decrypt` 抛 `ValueError`；无 secret 时 `encrypt` 抛 `RuntimeError`。用 `dataclasses.replace(secretbox.settings, file_secret=...)` + monkeypatch。
- [ ] **Step 2: 运行确认失败**（`ModuleNotFoundError`）。
- [ ] **Step 3: 实现** `secretbox.py`：Fernet，密钥 = `base64.urlsafe_b64encode(sha256(b"hub-secretbox:" + file_secret).digest())`；`decrypt` 捕获 `InvalidToken` 转 `ValueError("密钥无法解密")`。`settings_store.py` 用 `db.connect()` upsert / select；`db.SCHEMA` 加表。
- [ ] **Step 4: 运行通过**；跑全量 pytest 确认无回归。
- [ ] **Step 5: 提交** `feat: 密钥加密与中枢设置存储`。

### Task 2: 对话模型上游（New API 渠道）

**Files:**
- Create: `console/backend/app/model_upstreams.py`
- Modify: `console/backend/app/newapi.py`（渠道方法）、`console/backend/app/main.py`（路由）、`console/backend/app/providers/demo.py` 与 `providers/casdoor.py`（`catalog()["models"]` 用真实可用模型，网关不可用时保持原样）
- Test: `console/backend/tests/test_model_upstreams.py`

**Interfaces:**
- Consumes: `NewApi._call`、`NewApi.available_models()`、`secretbox.mask_secret`。
- Produces（`NewApi` 新增）: `list_channels() -> list[dict]`、`create_channel(name, base_url, key, models: list[str]) -> int`、`update_channel(id, **fields) -> None`（可改 name/base_url/key/models/status，key 为 None 不改）、`delete_channel(id) -> None`、`fetch_models(base_url, key) -> list[str]`。
- Produces（`model_upstreams.py`）: `list_upstreams(na) -> list[dict]`，每项 `{id, name, base_url, models: [str], status: "enabled"|"disabled", key_hint: "••••1234"}`；`probe(na, base_url, key) -> {"models": [...]}`（失败抛 `UpstreamError(msg)`，msg 不含 key）；`add(na, name, base_url, key, models) -> dict`；`patch(na, id, *, name=None, base_url=None, key=None, models=None, enabled=None) -> dict`；`remove(na, id) -> None`。
- Produces（HTTP，均挂 `api` 路由）: `GET /api/models/upstreams`、`POST /api/models/upstreams/probe`（body `{base_url, key}`）、`POST /api/models/upstreams`（`{name, base_url, key, models}`）、`PATCH /api/models/upstreams/{id}`、`DELETE /api/models/upstreams/{id}`。网关未配置返回 503「未配置模型网关（NEWAPI_*）」；校验失败 400；每次写操作写审计。

- [ ] **Step 1: 先对真实 New API 探路**：用 `hub/.env` 里的 `NEWAPI_ACCESS_TOKEN` 实际调用渠道的创建 / 更新 / 删除 / 拉模型接口（先用 mock-llm 当上游），把真实字段名和响应形状记在 `newapi.py` 方法的 docstring 里；确认「没有价格倍率的模型能否被调用」，结论写进 `docs/mcp-server.md` 的模型小节（Task 6 汇总）。
- [ ] **Step 2: 写失败测试** `test_model_upstreams.py`，用 `httpx.MockTransport` 伪造 New API 响应：`list_upstreams` 返回字段正确且 `key_hint` 不含明文；`probe` 失败时异常信息不含 key；`patch(key=None)` 的请求体里没有 key 字段；`add` 的 `base_url` 必须 `http(s)://` 开头且去掉末尾 `/`，否则 `UpstreamError`；路由：未登录 401（`auth_enabled` 下）、网关未配置 503、成功后写审计且审计详情不含 key（monkeypatch `db.add_audit`）。
- [ ] **Step 3: 运行确认失败**。
- [ ] **Step 4: 实现** 上述 `NewApi` 方法（按 Step 1 的真实形状）、`model_upstreams.py`、`main.py` 路由，以及 `catalog()["models"]`：网关配置了就用 `available_models()` 的真实模型（`{"id", "name": id, "location": "上游", "rate": ""}`），否则保持原样。
- [ ] **Step 5: 运行通过**；全量 pytest。
- [ ] **Step 6: 真实验证**：对 mock-llm 走一遍「probe → add → 列表 → 岗位包候选出现 → 领取配置的 key 含该模型 → 用该 key 调一次成功 → disable 后再领取不含」，结果记录给 Task 6。
- [ ] **Step 7: 提交** `feat: 对话模型上游管理（New API 渠道读写与接口）`。

### Task 3: 出图 API 配置与 apimart 客户端

**Files:**
- Create: `console/backend/app/imageapi.py`
- Modify: `console/backend/app/main.py`（路由）
- Test: `console/backend/tests/test_imageapi.py`

**Interfaces:**
- Consumes: `secretbox`、`settings_store`。
- Produces: `imageapi.list_providers() -> list[dict]`（每项 `{id, name, kind: "apimart", base_url, model, enabled, key_hint}`）；`add_provider(name, base_url, model, key) -> dict`；`patch_provider(id, *, name=None, base_url=None, model=None, key=None, enabled=None) -> dict`；`remove_provider(id)`；`get_route() -> "gpu"|"api"`；`set_route(route)`（`"api"` 且无启用的 provider 抛 `ImageApiError("没有可用的出图 API")`）；`active_provider() -> dict | None`（含解密后的 key，仅内部用，不进接口）。
- Produces（客户端，类 `ApimartClient(base_url, key, model, client: httpx.Client | None = None)`）: `submit(prompt: str, width: int, height: int, count: int) -> str`（返回第三方任务号）、`poll(task_id) -> tuple[str, list[str]]`（状态 `"running"|"done"|"failed"`，完成时第二项为图片地址）、`download(url) -> bytes`、`test() -> dict`（最小尺寸跑一张，返回 `{"ok": bool, "seconds": float, "error": str}`）。
- Produces（HTTP）: `GET /api/models/image`（`{route, providers}`）、`POST /api/models/image/providers`、`PATCH/DELETE /api/models/image/providers/{id}`、`PUT /api/models/image/route`（`{route}`）、`POST /api/models/image/providers/{id}/test`。
- 提交 `POST {base_url}/v1/images/generations`（`Authorization: Bearer`，JSON 含 `model`、`prompt`、`size`、`n`），从响应 `data[0].task_id` 取任务号；轮询 `GET {base_url}/v1/tasks/{task_id}`，状态 `completed`→done、`failed`→failed、其他→running，完成取 `result.images[0].url[0]`。**以上字段来自 apimart 博客示例，实现时用真实调用核对，不符以实测为准并改测试。** `base_url` 配置为不带 `/v1` 的站点根（如 `https://api.apimart.ai`）；若用户填了以 `/v1` 结尾的地址，保存时去掉。

- [ ] **Step 1: 写失败测试** `test_imageapi.py`，用 `MockTransport` 伪造 apimart：提交返回 task_id、轮询 running→completed 序列、失败状态、HTTP 401/5xx 转 `ImageApiError`（信息不含 key）；`add_provider` 后 `list_providers` 的 `key_hint` 只有后四位，`settings_store` 里的值不含明文 key（monkeypatch store 为内存字典）；`patch_provider(key=None)` 不改密文；`set_route("api")` 无启用 provider 抛错；路由层审计不含 key。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** `imageapi.py` 与路由（store 键 `image.providers`、`image.route`；provider id 用 `uuid4().hex[:8]`）；`test()` 的最小图用 `512x512`、`count=1`，轮询上限 120 秒。
- [ ] **Step 4: 运行通过**；全量 pytest。
- [ ] **Step 5: 真实验证**：管理员在页面填入真实 apimart key 后再做（Task 6）；此处只确认 mock 通过。
- [ ] **Step 6: 提交** `feat: 出图 API 配置与 apimart 客户端`。

### Task 4: 把 API 出图接进任务流水线

**Files:**
- Modify: `console/backend/app/generation.py`（提交时按通道选 workflow）、`console/backend/app/db.py`（`claim_task_for` 排除 `api-image`；新增 `claim_api_tasks(limit)`、`gpu_seconds_this_month` 排除 `api-image`）、`console/backend/app/gpu.py`（worker API 分支、`list_tasks` 增加通道字段）、`console/backend/app/config.py`（`image_api_max_concurrency`，环境变量 `HUB_IMAGE_API_CONCURRENCY`，默认 4）
- Test: `console/backend/tests/test_gpu_api_route.py`

**Interfaces:**
- Consumes: `imageapi.get_route/active_provider/ApimartClient`。
- Produces: `generation.submit_cover/submit_image` 在 `imageapi.get_route() == "api"` 时提交 workflow `"api-image"`（参数不变，另带 `params["_channel"]="api"`）；`db.claim_api_tasks(limit: int) -> list[dict]`（把排队中的 `api-image` 任务置 running，已 running 的 api 任务数 + 新领 ≤ limit）；`gpu.run_api_step(client_factory=ApimartClient) -> None`（一轮：领取新任务并提交、轮询在跑任务）；`describe` 不变；`list_tasks` 每个任务多一个 `"via": "本机 GPU"|"第三方 API"`。
- 行为：提交后立刻把第三方任务号写入 `prompt_id`（`db.update_gpu_task`）；`count>1` 时按接口能力一次提交 `n=count`，若接口只返回部分图则以实际返回为准；完成后逐张 `download` 存 `outputs/<task_id>/<i>.<ext>` 并 `status=done`、写「生成」审计（详情写「第三方 API」与耗时）；失败 / 异常 / 空图 → `status=failed` + 审计；运行超过 `API_TIMEOUT_SECONDS`（600）→ 失败；网络抖动（`httpx.HTTPError`）下一轮再查；重启后 `prompt_id` 已有的在跑任务直接继续轮询，不重新提交。

- [ ] **Step 1: 写失败测试** `test_gpu_api_route.py`（内存假 db，沿用 `test_gpu_recovery.py` 的做法）：通道为 gpu 时仍是 `image-gen`；通道为 api 时是 `api-image`；`claim_task_for` 不领取 api 任务；`gpu_seconds_this_month` 不含 api 任务；`run_api_step` 提交→写 `prompt_id`→下一轮 poll 完成→文件落盘→done；失败状态 → failed + 审计；空图 → failed；超时 → failed；已有 `prompt_id` 的 running 任务不重复 `submit`；并发上限生效（5 个排队、上限 4 → 只领 4 个）；切通道后旧任务 workflow 不变。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** 上述各处；worker 主循环（`run_worker`）每轮调用 `run_api_step`（出错只记日志）。
- [ ] **Step 4: 运行通过**；全量 pytest。
- [ ] **Step 5: 提交** `feat: API 出图接入任务队列（通道开关、worker 分支）`。

### Task 5: 前端「模型」页

**Files:**
- Create: `console/frontend/src/pages/Models.tsx`
- Modify: `console/frontend/src/api.ts`、`console/frontend/src/main.tsx`、`console/frontend/src/layout/ConsoleLayout.tsx`（「能力」分组加「模型」，图标 `Cpu`）、`console/frontend/src/pages/Tasks.tsx`（任务行显示通道，如已有「节点」列则并入）
- 验证：`npx tsc -b`、`npx oxlint src`、浏览器看亮 / 暗两套主题。

**Interfaces:**
- Consumes: Task 2、3 的 HTTP 接口。
- Produces: `api.upstreams()`、`api.probeUpstream(body)`、`api.addUpstream(body)`、`api.patchUpstream(id, body)`、`api.deleteUpstream(id)`、`api.imageConfig()`、`api.addImageProvider(body)`、`api.patchImageProvider(id, body)`、`api.deleteImageProvider(id)`、`api.setImageRoute(route)`、`api.testImageProvider(id)`，类型 `Upstream`、`ImageProvider`、`ImageConfig`。

- [ ] **Step 1:** 在 `api.ts` 加类型和上述方法。
- [ ] **Step 2:** `Models.tsx` 两个分区：「对话模型」表格（名称、地址、开放的模型 Token、状态开关、操作）+ 添加 / 编辑抽屉（名称、地址、密钥〔编辑时留空不改〕、「测试连接」按钮拉模型后多选）；「出图通道」卡片（当前通道分段切换「本机 GPU / 第三方 API」，无可用出图 API 时切换置灰并提示原因）+ 出图 API 表格与添加 / 编辑抽屉（名称、地址、模型名、密钥）+ 每行「测试」按钮显示耗时与结果。沿用 `Panel`、`PageHeader`、`Pill`、`Token`、`Empty`；表单提交失败显示后端 `detail`。
- [ ] **Step 3:** 路由、导航、`TITLES`；`Tasks.tsx` 显示通道。
- [ ] **Step 4:** `npx tsc -b` 与 `npx oxlint src` 无新增错误。
- [ ] **Step 5:** 重建 `console-web`，浏览器里走一遍两个分区的添加 / 编辑 / 删除 / 切换，亮暗主题各看一次。
- [ ] **Step 6: 提交** `feat: 控制台「模型」页`。

### Task 6: 真实端到端、文档与收尾

**Files:**
- Modify: `docs/mcp-server.md`、`docs/gpu.md`、`hub/README.md`（说明新页面与出图通道）；视需要 `docs/agent.md`

- [ ] **Step 1:** 重建 `console-api`、`hub-mcp`、`hub-worker`、`console-web`，对真实 New API + 真实 Postgres 完整验证 Task 2 Step 6 的链路（如已验证则记录结果）。
- [ ] **Step 2:** 用 mock 的 apimart 兼容小服务（临时脚本，放 scratchpad）端到端：页面接口添加出图 API → 切到 API → 经 MCP `generate_image` 提交 → worker 轮询 → 图片落盘并拿到中枢签发链接；再切回 GPU 验证新任务走 ComfyUI mock。
- [ ] **Step 3:** 文档：新页面使用方法、两条出图线的区别与切换、密钥存放方式、`HUB_IMAGE_API_CONCURRENCY`、已知限制（不计费用、视频仍走本机）。
- [ ] **Step 4:** 全量 `pytest` + `npx tsc -b`；整个分支做一次自我审查（对照 Review Focus 五条）；提交 `docs: 模型页与出图通道说明`。
- [ ] **Step 5:** 询问用户填入真实 apimart key 做最后一次真实出图验证，以及是否推送（排除 `windows节点搭建任务书.md`）。
