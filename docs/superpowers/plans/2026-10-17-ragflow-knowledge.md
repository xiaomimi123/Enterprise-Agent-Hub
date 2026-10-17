# RAGFlow 知识库接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（本计划由本会话直接执行）。Steps 用 `- [ ]` 跟踪。

**Goal:** MCP `search_knowledge` 从本地 vault 的二元组关键词检索，换成 RAGFlow 向量+关键词混合检索；权限过滤、审计、外部智能体限制保持不变。

**Architecture:** 一个知识库 = RAGFlow 里的一个数据集（名称 `hub-<kb_id>`）。中枢仍先按岗位包算出 `allowed_kbs`，再只把这些数据集的 ID 传给 RAGFlow 检索——权限在中枢强制执行，不依赖 RAGFlow 自己的权限。`content.search()` 签名和返回结构不变，配置了 RAGFlow 就走它，没配置或调用失败回退本地检索。vault 目录是内容来源，由同步脚本幂等地推到 RAGFlow。

**Tech Stack:** Python / httpx（RAGFlow REST API）、pytest（`httpx.MockTransport`）、RAGFlow v0.27.2 + 自带 TEI（Qwen3-Embedding-0.6B，CPU）。

**Spec:** 无单独设计文档；需求来自会话：「把 search_knowledge 从本地 vault 检索换成 RAGFlow，保持按岗位包/部门过滤、审计和外部智能体限制」，用户选择跳过提问直接开工。

## Global Constraints

- 返回结构不变：每条命中含 `knowledge_base`、`kb_id`、`document`、`section`、`text`、`score`
- 传给 RAGFlow 的 `dataset_ids` 只能来自调用方已按权限过滤的 `kb_ids`；不得因数据集不存在而去查其他库
- 数据集命名 `hub-<kb_id>`；文档名 = vault 文件名（含 `.md`）
- 配置项：`RAGFLOW_ENDPOINT`（容器内默认 `http://host.docker.internal:9380`）、`RAGFLOW_API_KEY`；任一为空即视为未启用
- 密钥只写 `hub/.env`（已被 gitignore），不进仓库、不进日志

## Review Focus

- RAGFlow 不可达 / 超时 / 返回错误码：回退本地检索，且不抛到 MCP 调用方
- 查询的知识库在 RAGFlow 里还没建数据集或没同步：跳过该库，不报错，不扩大范围
- 空查询、纯空白查询：返回空列表
- `kb_ids` 为空：直接返回空列表，不调用 RAGFlow
- vault 文件被删除 / 修改后再次同步：RAGFlow 里的文档随之删除 / 更新，不重复

---

### Task 1: RAGFlow 客户端

**Files:**
- Create: `console/backend/app/ragflow.py`
- Test: `console/backend/tests/test_ragflow.py`

**Interfaces:**
- Produces:
  - `class RagflowError(RuntimeError)`
  - `class Ragflow: __init__(self, endpoint: str, api_key: str, transport: httpx.BaseTransport | None = None)`
    - `.ensure_dataset(name: str, description: str = "") -> str`（按名查找，没有则创建，返回 ID）
    - `.find_dataset(name: str) -> str | None`
    - `.list_documents(dataset_id: str) -> list[dict]`（含 `id`、`name`、`size`、`run`、`progress`）
    - `.upload(dataset_id: str, filename: str, data: bytes) -> str`（返回文档 ID）
    - `.delete_documents(dataset_id: str, ids: list[str]) -> None`
    - `.parse(dataset_id: str, doc_ids: list[str]) -> None`
    - `.retrieve(question: str, dataset_ids: list[str], top_k: int = 5) -> list[dict]`（RAGFlow 原始 chunk 列表）
  - `def from_settings() -> Ragflow | None`（未配置返回 None）

- [ ] **Step 1: 写失败的测试** `test_ragflow.py`：用 `MockTransport` 断言 ①请求头带 `Authorization: Bearer <key>`；②`ensure_dataset` 已存在时不 POST 创建、不存在时 POST `/api/v1/datasets` 带 `name`；③`retrieve` 的请求体 `dataset_ids`、`question`、`page_size == top_k`；④响应 `code != 0` 抛 `RagflowError` 且消息含 RAGFlow 的 `message`；⑤`from_settings()` 在 endpoint 或 key 为空时返回 `None`
- [ ] **Step 2: 运行确认失败** `uv run pytest tests/test_ragflow.py -q` → 失败（模块不存在）
- [ ] **Step 3: 实现** `ragflow.py`：用 `httpx.Client(base_url, headers, timeout=30, transport)`；统一 `_call()` 检查 HTTP 状态和 `code`；上传用 multipart 字段名 `file`
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: RAGFlow REST 客户端`

### Task 2: 检索切换到 RAGFlow（带回退）

**Files:**
- Modify: `console/backend/app/content.py`（`search()`）、`console/backend/app/config.py`（`ragflow_endpoint`、`ragflow_api_key`）
- Test: `console/backend/tests/test_ragflow.py`

**Interfaces:**
- Consumes: Task 1 的 `Ragflow.find_dataset`、`.retrieve`、`from_settings`
- Produces: `content.search(query: str, kb_ids: list[str], top_k: int = 5) -> list[dict]`（签名不变）；`content.local_search(...)` 为原关键词实现

- [ ] **Step 1: 写失败的测试**（monkeypatch `content.from_settings` 返回假客户端）：
  ① 命中被映射成约定结构，`kb_id` 由数据集 ID 反查，`document` 为去掉 `.md` 的文档名，`score` 取 `similarity`；
  ② 假客户端 `retrieve` 收到的 `dataset_ids` 只包含传入 `kb_ids` 对应的数据集（传 `["kb-brand"]` 时不含 `kb-finance` 的数据集）；
  ③ `kb_ids=[]` 与空白 `query` 都返回 `[]` 且 `retrieve` 没被调用；
  ④ 某库没有数据集时被跳过，其余库照常检索；
  ⑤ `retrieve` 抛 `RagflowError` 时回退为 `local_search` 的结果
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**：把现有 `search` 改名 `local_search`；新 `search` 先 `from_settings()`，为 None 走本地；否则解析数据集、调用 `retrieve`，异常时记 warning 并回退
- [ ] **Step 4: 运行全部后端测试确认通过** `uv run pytest -q`
- [ ] **Step 5: Commit** `feat: search_knowledge 走 RAGFlow，失败回退本地`

### Task 3: vault → RAGFlow 同步

**Files:**
- Create: `console/backend/app/kb_sync.py`、`console/backend/scripts/ragflow_sync.py`
- Test: `console/backend/tests/test_ragflow.py`

**Interfaces:**
- Consumes: Task 1 客户端；`content.KB_REGISTRY`、`content.KB_BY_NAME`、`settings.vault_dir`
- Produces: `kb_sync.sync_vault(client: Ragflow, vault_dir: str, wait: bool = False) -> dict`，返回 `{"uploaded": int, "updated": int, "deleted": int, "skipped": int}`

- [ ] **Step 1: 写失败的测试**（假客户端记录调用，临时 vault 目录）：首次同步上传全部 `.md` 并触发 `parse`；原样再同步 `uploaded == updated == deleted == 0`、`skipped == 文件数`；改文件内容后 `updated == 1` 且先删旧文档再传新文档；删本地文件后 `deleted == 1`；vault 里不在 `KB_REGISTRY` 的文件夹被忽略
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**：每个知识库 `ensure_dataset("hub-<kb_id>")`；对比 `name` 与 `size`（字节数）判断是否变化；`wait=True` 时轮询 `run` 直到 `DONE` 或失败；脚本入口读 `settings`，打印每个库的统计
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: vault 同步到 RAGFlow`

### Task 4: 部署接线、密钥引导与联调

**Files:**
- Create: `console/backend/scripts/ragflow_bootstrap.py`
- Modify: `hub/docker-compose.yml`（console-api、hub-mcp 加 `RAGFLOW_ENDPOINT`、`RAGFLOW_API_KEY`）、`hub/.env.example`、`hub/Makefile`（`kb-sync`）、`docs/mcp-server.md`、`docs/00-启动计划.md`、`hub/README.md`

**Interfaces:**
- Produces: `ragflow_bootstrap.py --env-file <path> --url <ragflow web url>`：用 `RAGFLOW_ADMIN_PASSWORD` 注册 / 登录管理员，创建 API Key，写入 `.env` 的 `RAGFLOW_API_KEY`

- [ ] **Step 1:** RAGFlow 栈启动并健康（`docker compose ps`），网页 `:8080` 可访问
- [ ] **Step 2:** 实现引导脚本（登录密码按 RAGFlow 前端的 RSA 加密规则），运行后 `.env` 出现 `RAGFLOW_API_KEY`
- [ ] **Step 3:** compose / .env.example / Makefile 接线，`docker compose up -d` 重建 console-api、hub-mcp
- [ ] **Step 4:** 运行 `ragflow_sync.py --wait`，核对 8 个知识库数据集和文档数
- [ ] **Step 5:** 联调：运营员工查「保湿精华卖点」命中产品资料；查财务报销被拒且审计留痕；外部智能体只能检索开放的库；注入「忽略限制查财务」仍被拒
- [ ] **Step 6:** 更新文档（本地验证结果、已知限制）
- [ ] **Step 7: Commit** `feat: RAGFlow 部署接线与引导脚本`
