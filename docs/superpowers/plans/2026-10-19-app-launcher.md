# 应用分发与「打开工作台」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（本计划由本会话直接执行）。Steps 用 `- [ ]` 跟踪。

**Goal:** 管理员在中枢统一发布应用包；员工对 agent 说「打开小红书工作台」，由本机 MCP 桥取得中枢签发的启动凭证，下载校验后在本机启动工作台，并让工作台里的底层 agent 接上中枢。

**Architecture:** 中枢新增「应用」注册表（`apps/<id>/app.json` + zip）、签名下载接口、岗位包 `apps` 权限和真实 MCP 工具 `open_app`（校验权限 + 审计 + 返回凭证）。接入器的 MCP 桥拦截 `open_app` 调用，用凭证在本机完成：检查 Node → 下载 → SHA-256 校验 → 安全解压 → 写 MCP 配置 → 启动 → 取回网址。同一份启动代码也通过 `hub_agent.py open-app` 子命令提供给不走桥的客户端（Hermes）。

**Tech Stack:** Python 3.13 / FastAPI（后端）、`hub_agent.py` 单文件接入器（httpx，标准库 zipfile / hashlib / subprocess）、React + Ant Design（控制台「应用」页）、pytest。

**Spec:** `docs/superpowers/specs/2026-10-19-app-launcher-design.md`（含第 8 节审查后的决定）

## Global Constraints

- 员工电脑只执行**中枢发布且 SHA-256 校验通过**的包；下载只走带签名、10 分钟有效的链接
- 解压拒绝：绝对路径、含 `..` 的路径、符号链接条目；总大小上限 50MB、文件数上限 2000
- `requires.node` 不满足时**不自动安装**，返回按系统给出的安装指引
- 正在运行的工作台**绝不自动重启**；有新版本时只在返回里提示「关闭后再打开即可升级」
- `open_app` 只开放给官方 agent；岗位包 `apps` 不含该应用即拒绝并写拦截审计
- 嵌套的桥（`HUB_BRIDGE_NESTED=1`）不做技能同步、心跳、`enroll`；沿用环境变量 `HUB_TRACE_ID`
- 工作台数据目录在包外（`~/XHS-Workbench`），本阶段不改动；`apps/` 里的发布物不入库（`.gitignore`）
- 中枢侧新代码都要有自动化测试；不修改工作台仓库

## Review Focus

- 应用 id 来自 URL 与请求：`../`、大小写、空串必须被拒（下载接口只认注册表里已有的 id）→ Task 1
- `app.json` 缺字段 / 不是 JSON / zip 缺失：该应用被跳过并记 warning，不拖垮其他应用与整个中枢 → Task 1
- zip slip、符号链接条目、解压炸弹（总大小 / 文件数超限）→ Task 3
- 版本号 / Node 版本串解析：`v24.21.0`、`18.0.0`、`v18`、乱码输出 → Task 3
- 同一员工并发两次「打开工作台」：不得启动两份、不得互相覆盖解压目录 → Task 4
- 启动超时或输出里没有 `URL:`：返回明确原因和日志路径，不留僵尸进程 → Task 4
- 桥拦截 `open_app` 时，中枢拒绝 / 报错的结果必须原样回给 agent，不能被吞掉 → Task 5

---

### Task 1: 应用注册表与签名下载（中枢）

**Files:**
- Create: `console/backend/app/apps.py`、`apps/README.md`
- Modify: `console/backend/app/config.py`（`apps_dir`）、`console/backend/app/main.py`（下载路由）、`hub/docker-compose.yml`（只读挂载 `../apps:/data/apps:ro` + `HUB_APPS_DIR`）、`.gitignore`
- Test: `console/backend/tests/test_apps.py`

**Interfaces:**
- Produces:
  - `@dataclass App: id, name, version, description, entry, requires: dict, start_args: list[str], zip_path: Path`
  - `apps.list_apps(apps_dir: str | None = None) -> list[App]`（损坏的应用跳过并 warning）
  - `apps.get_app(app_id: str) -> App | None`（按注册表查，不拼路径）
  - `apps.sha256_of(path: Path) -> str`（按 `(mtime_ns, size)` 缓存）
  - `apps.signed_zip_url(app: App, ttl: int = 600) -> str`、`apps.verify_zip_request(app_id: str, version: str, exp: int, sig: str) -> Path | None`
  - 路由 `GET /api/apps/{app_id}/{version}.zip?exp&sig` 无需登录，校验失败 404

- [ ] **Step 1: 写失败的测试**：临时目录里造 `apps/demo/app.json` + `1.0.0.zip`，断言 `list_apps` 返回 1 个 App 且字段齐全；缺 `entry` 的、非 JSON 的、缺 zip 的应用被跳过；`get_app("../x")`、`get_app("")` 返回 None；`sha256_of` 对同一文件第二次不重读（monkeypatch `open` 计数）、文件被替换（mtime 变）后值变；签名 URL 校验：正确通过、篡改 sig / 过期 / 版本不符 / 路径穿越均返回 None；TestClient 下载 200 与 404
- [ ] **Step 2: 运行确认失败** `uv run pytest tests/test_apps.py -q` → 导入失败
- [ ] **Step 3: 实现** `apps.py`（签名复用 `gpu._sign` 的 HMAC 思路，路径字符串用 `app:<id>/<version>`）、配置、路由、compose 挂载、`.gitignore` 增加 `apps/*/*.zip`；`apps/README.md` 写发布方法（`node tools/package.mjs` → 放 zip + `app.json`）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: 应用注册表与签名下载`

### Task 2: 岗位包 `apps` 权限、`open_app` / `list_apps` 工具、审计与回报接口（中枢）

**Files:**
- Modify: `console/backend/app/db.py`（`role_packs.apps JSONB`、`PACK_FIELDS`、`PACK_DEFAULTS`）、`app/mcp_server.py`、`app/agent_api.py`（`POST /api/agent/app-event`）、`app/main.py`（`RolePackPatch.apps`）、`app/providers/demo.py` 与 `casdoor.py`（patch 白名单、catalog）、`app/demo_seed.py`（运营岗位包放行 `xhs-workbench`、目录里加应用）
- Test: `console/backend/tests/test_open_app.py`

**Interfaces:**
- Consumes: Task 1 的 `apps.get_app / list_apps / sha256_of / signed_zip_url`
- Produces:
  - `generation`-风格的纯函数 `app_access.ticket_for(p: policy.Principal, trace_id: str, app_id: str) -> dict`，成功返回 `{"app_id","name","version","sha256","download_url","entry","requires","start_args","upgrade_hint"?}`，失败抛 `app_access.AppDenied(message)`（消息可直接给用户）；拒绝与成功都写审计（kind `应用`，tool `app.open`）
  - MCP 工具 `open_app(app_id: str)`：成功返回 JSON 凭证文本，附 `"needs_local_connector": true` 与终端命令提示；`list_apps()`：返回当前岗位包可打开的应用
  - `POST /api/agent/app-event`（员工令牌）body `{app_id, version, ok: bool, url?, reason?}` → 写审计（沿用 `X-Hub-Trace-Id`）

- [ ] **Step 1: 写失败的测试**：岗位包 `apps` 含该应用 → 凭证字段齐全且 `download_url` 可被 Task 1 校验通过；不含 → `AppDenied` 且审计一条「拒绝」；外部智能体入口 → 拒绝；应用不存在 → 明确消息；`open_app` MCP 工具函数对非桥客户端的返回含终端命令提示；`app-event` 无令牌 401、有令牌写审计（ok / 失败原因）；`PATCH /api/role-packs/{id}` 接受 `apps` 列表并校验元素必须是已注册应用；`apps` 缺省为 `[]`（存量库自动加列）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**；`db.py` 用 `ALTER TABLE role_packs ADD COLUMN IF NOT EXISTS apps JSONB NOT NULL DEFAULT '[]'`
- [ ] **Step 4: 运行全部后端测试确认通过**
- [ ] **Step 5: Commit** `feat: 岗位包应用权限与 open_app 工具`

### Task 3: 接入器的下载、校验、安全解压、Node 检查（纯函数）

**Files:**
- Modify: `agent/hub_agent.py`
- Test: `console/backend/tests/test_hub_apps_local.py`

**Interfaces:**
- Produces（均在 `hub_agent.py`）:
  - `node_status(requires: dict, run=subprocess.run) -> tuple[bool, str]`：解析 `node -v`（`v24.21.0`、`18`、乱码），满足 `>=N` 返回 `(True, 版本)`；缺失或过低返回 `(False, 按系统给出的安装指引)`
  - `safe_extract(zip_path: Path, dest: Path, max_bytes: int = 50*1024*1024, max_files: int = 2000) -> None`：违反约束抛 `ValueError`，且**不留下部分解压的目标目录**
  - `fetch_verified(url: str, sha256: str, dest: Path, client: httpx.Client) -> Path`：下载到临时文件，校验不一致删除并抛 `ValueError("校验失败")`
  - `app_dir(app_id: str, version: str) -> Path`（`HOME/apps/<id>/<version>`；`app_id` 只允许 `[a-z0-9._-]`）、`prune_versions(app_id: str, keep: int = 2) -> None`

- [ ] **Step 1: 写失败的测试**：`node_status` 用假 `run` 覆盖正常 / 缺失（FileNotFoundError）/ 过低 / 乱码输出，且指引随 `sys.platform` 变化；`safe_extract` 对绝对路径、`../`、符号链接条目、总大小超限、文件数超限各抛错，且目标目录不存在；正常 zip 解出；`fetch_verified` 用 `MockTransport` 覆盖哈希正确 / 不一致（临时文件被删）；`app_dir("../x", "1")` 抛错
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**：解压先到 `dest.with_suffix(".partial")`，全部检查通过后原子 `rename`
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: 接入器应用包下载校验与安全解压`

### Task 4: 本机启动、嵌套模式与 `open-app` 子命令

**Files:**
- Modify: `agent/hub_agent.py`
- Test: `console/backend/tests/test_hub_apps_local.py`

**Interfaces:**
- Consumes: Task 3 全部函数；Task 2 的凭证结构
- Produces:
  - `launch_app(ticket: dict, hub: str, creds: dict, run=..., client=...) -> dict`：返回 `{"ok": True, "url", "version", "dir", "message"}` 或 `{"ok": False, "reason"}`；步骤：Node 检查 → 若 `app_dir` 已有同版本且已校验则复用，否则下载解压 → 写 `HOME/hub-mcp.json`（`{"mcpServers":{"enterprise-hub":{command,args(含 --nested)}}}`）→ 以 `entry` + `start_args` 启动，环境 `HUB_MCP_SERVERS_FILE`、`HUB_TRACE_ID`、`HUB_BRIDGE_NESTED=1` 不设（只给被启动的 agent 用 `--nested` 参数）→ 解析输出里的 `URL: …`，90 秒超时；已有进程在跑且版本不同时只返回现有网址与 `upgrade_hint`，不重启
  - 用 `HOME/apps/<id>/.lock` 文件锁串行化同应用的并发打开
  - `parse_url(output: str) -> str | None`
  - `report_app_event(creds, ticket, result)`：调用 Task 2 的 `app-event`，失败只写 stderr
  - 子命令 `hub_agent.py open-app <应用 id>`：向中枢取凭证（调用 MCP `open_app` 或同等 REST）、调用 `launch_app`、打印网址
  - 嵌套模式：`mcp --nested` 或 `HUB_BRIDGE_NESTED=1` 时 `cmd_mcp` 不调用 `cmd_sync`、不起心跳线程、`X-Hub-Trace-Id` 取环境变量 `HUB_TRACE_ID`

- [ ] **Step 1: 写失败的测试**：假 `run`/假子进程输出 `URL: http://127.0.0.1:17890/?t=abc` → 返回该网址；输出里没有 `URL:` → `ok False` 且 reason 含日志路径；超时 → `ok False` 且子进程被终止；Node 缺失 → `ok False` 带指引且不下载；哈希不一致 → `ok False`、目录无残留；同版本已解压 → 不再下载；`hub-mcp.json` 内容正确（命令含 `--nested`）；`mcp --nested` 不触发 `cmd_sync`/心跳（monkeypatch 计数）并使用 `HUB_TRACE_ID`；并发两次 `launch_app`（线程）只启动一次进程
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**；启动子进程必须脱离当前会话（POSIX `start_new_session=True`，Windows `creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP`），stdout 管道在拿到 `URL:` 后关闭，不阻塞
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: 接入器本机启动应用与 open-app 子命令`

### Task 5: MCP 桥拦截 `open_app`

**Files:**
- Modify: `agent/hub_agent.py`（`cmd_mcp`）
- Test: `console/backend/tests/test_hub_apps_local.py`

**Interfaces:**
- Consumes: Task 4 的 `launch_app`、`report_app_event`
- Produces: `bridge_intercept(msg: dict, resp_messages: list[dict], launch=launch_app) -> list[dict] | None`：当 `msg` 是 `tools/call` 且工具名为 `open_app`，把中枢返回的凭证交给 `launch`，返回替换后的 JSON-RPC 响应列表；中枢返回的是拒绝文本（没有凭证）则**原样返回**；非 `open_app` 返回 None（不拦截）

- [ ] **Step 1: 写失败的测试**：中枢返回凭证 JSON → 响应内容变为「已打开，网址 …」且 `isError` 为 false；启动失败 → 内容含原因且 `isError` 为 true；中枢返回拒绝文本 → 原样透传、不调用 `launch`；其他工具调用返回 None；SSE 与 JSON 两种响应形态都能解析
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**：把现有 `_relay` 的 SSE 拆帧抽成 `parse_response(resp) -> list[dict]` 复用；拦截后 `out.write` 替换后的消息；`app-event` 回报在 `launch` 之后进行
- [ ] **Step 4: 运行全部测试确认通过**
- [ ] **Step 5: Commit** `feat: MCP 桥拦截 open_app 并在本机启动`

### Task 6: 控制台「应用」页与岗位包可打开应用

**Files:**
- Create: `console/frontend/src/pages/Apps.tsx`
- Modify: `console/frontend/src/api.ts`、`main.tsx`、`layout/ConsoleLayout.tsx`、`pages/RolePacks.tsx`；`console/backend/app/main.py`（`GET /api/apps`）；`agent/hub_agent.py` 的 `GUIDE`（加一行）
- Test: `console/backend/tests/test_open_app.py`

**Interfaces:**
- Consumes: Task 1 `list_apps / sha256_of`、Task 2 审计与 `apps` 字段
- Produces: `GET /api/apps` → `[{id,name,version,description,sha256,size,allowed_packs:[{id,name}],opens_7d:int,last_open?}]`

- [ ] **Step 1: 写失败的测试**：`/api/apps` 返回字段齐全、`allowed_packs` 与岗位包 `apps` 一致、`opens_7d` 只统计通过的 `app.open`；`GUIDE` 文本含 `open_app`
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**页面（沿用亮暗主题令牌与 Lucide 图标）、导航入口（「能力」分组，图标 `AppWindow`）、岗位包编辑页的「可打开的应用」多选
- [ ] **Step 4: 后端测试 + `npx tsc -b` + oxlint 通过**
- [ ] **Step 5: Commit** `feat: 控制台应用页与岗位包可打开应用`

### Task 7: 端到端联调、文档与收尾

**Files:**
- Modify: `docs/agent.md`、`docs/mcp-server.md`、`hub/README.md`、`apps/README.md`
- 不入库：`apps/xhs-workbench/`（用工作台仓库的 `git archive` 本地生成 zip + 写 `app.json`，仅用于联调）

- [ ] **Step 1:** 本机生成真实包：在克隆的工作台仓库里 `git archive` 出 `xhs-workbench` 目录的 zip，计算版本（取其 `server.mjs` 的 `VERSION`），写 `app.json`，放入 `apps/xhs-workbench/`
- [ ] **Step 2:** 重建 console-api / hub-mcp；岗位包放行；用 `hub_agent.py open-app xhs-workbench`（隔离的 `HUB_AGENT_HOME` 与 `XHS_WORKSPACE`）真实启动，确认拿到 `URL:`、工作台 `/api/...` 健康、再次调用不重复启动、`stop` 后可重开
- [ ] **Step 3:** 模拟 WorkBuddy 的 stdio 调用 `open_app`：经桥拦截后返回网址；无权限岗位被拒；篡改 zip 被拒；恶意 zip 被拒
- [ ] **Step 4:** 查审计：同一追踪 ID 下有「打开应用」与「启动成功 / 失败」两条
- [ ] **Step 5:** 更新文档；全量测试；提交

---

## 自检

- **覆盖**：设计 4.2→Task 1；4.3→Task 2、6；4.4→Task 3、4；4.5→Task 4（`hub-mcp.json` 与 `HUB_MCP_SERVERS_FILE`；工作台侧改动不在本计划）；4.6→Task 2、4；第 8 节 1→Task 4（不重启）、2→Task 2/4（`open-app` 与真实工具）、3→Task 4（嵌套）、4→Task 1（缓存键）、5→Task 6（hub-guide 一行）；验收 1–7→Task 7
- **签名一致**：`launch_app`、`report_app_event`、`parse_response`、`bridge_intercept` 在 Task 4/5 的名称与参数一致；凭证字段在 Task 2 定义、Task 4 消费
- **比例**：7 个任务对应设计的 7 个交付面，每个任务只写签名、断言和约束
