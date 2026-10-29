"""中枢数据库（PostgreSQL）：岗位包、成员分配、审计事件。

控制台和 MCP Server 共用这一份数据：控制台负责配置岗位包和分配，MCP Server 据此做权限判断并写审计。
表结构在 init_schema() 里以 CREATE TABLE IF NOT EXISTS 创建，首次启动时把演示岗位包写入作为初始数据。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import demo_seed
from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS role_packs (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    dept             TEXT NOT NULL,
    status           TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    skills           JSONB NOT NULL DEFAULT '[]',
    knowledge_bases  JSONB NOT NULL DEFAULT '[]',
    tools            JSONB NOT NULL DEFAULT '[]',
    models           JSONB NOT NULL DEFAULT '[]',
    monthly_quota    INTEGER NOT NULL DEFAULT 0,
    max_action_level TEXT NOT NULL DEFAULT '需确认',
    external_access  TEXT NOT NULL DEFAULT '关闭',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 成员 → 岗位包。没有记录的成员按部门默认岗位包
CREATE TABLE IF NOT EXISTS role_assignments (
    org          TEXT NOT NULL,
    user_name    TEXT NOT NULL,
    role_pack_id TEXT NOT NULL REFERENCES role_packs(id),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org, user_name)
);

-- 审计事件：一次调用的一步一行，同一任务共用 trace_id
CREATE TABLE IF NOT EXISTS audit_events (
    id           BIGSERIAL PRIMARY KEY,
    trace_id     TEXT NOT NULL,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    org          TEXT NOT NULL,
    user_name    TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    dept         TEXT NOT NULL DEFAULT '',
    channel      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    tool         TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    result       TEXT NOT NULL,
    tokens       INTEGER NOT NULL DEFAULT 0,
    model        TEXT,
    cost         NUMERIC(12, 4) NOT NULL DEFAULT 0,
    summary      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_events_trace ON audit_events (trace_id);
CREATE INDEX IF NOT EXISTS audit_events_ts ON audit_events (ts DESC);

-- GPU 能力节点（由 HUB_GPU_NODES 同步），状态由调度服务定时刷新
CREATE TABLE IF NOT EXISTS gpu_nodes (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    url        TEXT NOT NULL,
    gpu        TEXT NOT NULL DEFAULT '',
    online     BOOLEAN NOT NULL DEFAULT false,
    vram_total BIGINT NOT NULL DEFAULT 0,
    vram_free  BIGINT NOT NULL DEFAULT 0,
    last_seen  TIMESTAMPTZ
);

-- GPU 任务队列：queued → running → done / failed
CREATE TABLE IF NOT EXISTS gpu_tasks (
    id          TEXT PRIMARY KEY,
    trace_id    TEXT NOT NULL,
    org         TEXT NOT NULL,
    user_name   TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    dept        TEXT NOT NULL DEFAULT '',
    channel     TEXT NOT NULL DEFAULT '',
    workflow    TEXT NOT NULL,
    params      JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'queued',
    node_id     TEXT,
    prompt_id   TEXT,
    images      JSONB NOT NULL DEFAULT '[]',
    error       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS gpu_tasks_status ON gpu_tasks (status, created_at);

-- 计费：岗位包选模型方式（中枢模型 / 自带模型），以及每人每月 GPU 分钟额度（0 = 不限）
ALTER TABLE role_packs ADD COLUMN IF NOT EXISTS model_mode TEXT NOT NULL DEFAULT '中枢模型';
ALTER TABLE role_packs ADD COLUMN IF NOT EXISTS gpu_quota_minutes INTEGER NOT NULL DEFAULT 0;
-- 可在员工本机打开的应用（apps/ 里注册的应用 id）
ALTER TABLE role_packs ADD COLUMN IF NOT EXISTS apps JSONB NOT NULL DEFAULT '[]';
-- 容错：任务被改派过几次（节点掉线 / 超时后重新排队）
ALTER TABLE gpu_tasks ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

-- 管理员在控制台里改的配置（出图通道、出图 API 等），值为 JSON
CREATE TABLE IF NOT EXISTS hub_settings (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 员工端在线状态：接入器报到或官方 agent 调用工具时刷新
CREATE TABLE IF NOT EXISTS agent_presence_daily (
    org       TEXT NOT NULL,
    day       DATE NOT NULL,
    user_name TEXT NOT NULL,
    PRIMARY KEY (org, day, user_name)
);

CREATE TABLE IF NOT EXISTS agent_presence (
    org       TEXT NOT NULL,
    user_name TEXT NOT NULL,
    client    TEXT,
    version   TEXT,
    os        TEXT,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org, user_name)
);

-- 控制台角色：老板（看全公司）、部门主管（只看和管自己部门）。管理员仍是 Casdoor 的 isAdmin
CREATE TABLE IF NOT EXISTS console_roles (
    org       TEXT NOT NULL,
    user_name TEXT NOT NULL,
    role      TEXT NOT NULL,               -- boss | manager
    dept_id   TEXT NOT NULL DEFAULT '',    -- manager 时是部门（Casdoor 分组名），boss 时为空
    PRIMARY KEY (org, user_name, role, dept_id)
);
-- 部门配置：默认岗位包（没有分配记录的成员按它走）
CREATE TABLE IF NOT EXISTS dept_config (
    org          TEXT NOT NULL,
    dept_id      TEXT NOT NULL,
    role_pack_id TEXT NOT NULL REFERENCES role_packs(id),
    PRIMARY KEY (org, dept_id)
);

-- 技能（SKILL.md）：控制台里编辑，带版本。skills/ 目录只在首次启动时导入为第 1 版
CREATE TABLE IF NOT EXISTS skills (
    id                TEXT PRIMARY KEY,
    dept_id           TEXT NOT NULL,             -- 部门（Casdoor 分组名）或 all（全公司）
    name              TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL DEFAULT '',
    published_version INTEGER NOT NULL DEFAULT 0, -- 0 = 还没有已发布的版本（新建后等审核）
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS skill_versions (
    skill_id    TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,                   -- published | pending | rejected
    reviewer    TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (skill_id, version)
);

-- 知识库文档（Markdown）：控制台里编辑，带版本；vault/ 目录只在首次启动时导入为第 1 版
CREATE TABLE IF NOT EXISTS kb_docs (
    kb_id             TEXT NOT NULL,
    name              TEXT NOT NULL,                 -- 文档名（不含 .md）
    published_version INTEGER NOT NULL DEFAULT 0,    -- 0 = 还没有已发布的版本
    synced_version    INTEGER NOT NULL DEFAULT 0,    -- 已同步到检索索引（RAGFlow）的版本
    deleted           BOOLEAN NOT NULL DEFAULT false,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kb_id, name)
);
CREATE TABLE IF NOT EXISTS kb_doc_versions (
    kb_id       TEXT NOT NULL,
    name        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    is_delete   BOOLEAN NOT NULL DEFAULT false,      -- 这一版是「删除」
    author      TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,                       -- published | pending | rejected
    reviewer    TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kb_id, name, version),
    FOREIGN KEY (kb_id, name) REFERENCES kb_docs (kb_id, name) ON DELETE CASCADE
);

-- 知识库本身：名称、部门、密级、内容类型、负责人、复核周期。首次启动从 demo_seed.KNOWLEDGE_BASES 导入，之后以此表为准
CREATE TABLE IF NOT EXISTS kbs (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    dept_id           TEXT NOT NULL,               -- 部门（Casdoor 分组名）或 all
    classification    TEXT NOT NULL,               -- 公开 | 内部 | 机密
    external_access   BOOLEAN NOT NULL DEFAULT false,
    source            TEXT NOT NULL DEFAULT '控制台',
    category          TEXT NOT NULL DEFAULT '其他',  -- 内容类型
    owner             TEXT NOT NULL DEFAULT '',    -- 负责人（用户名）
    review_every_days INTEGER NOT NULL DEFAULT 90, -- 复核周期，0 = 不需要复核
    last_reviewed_at  TIMESTAMPTZ,
    description       TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 改进建议：员工的 agent 对技能 / 知识库文档提出的修改建议，由负责的主管（全公司内容由老板 / 管理员）审核后才会生效
CREATE TABLE IF NOT EXISTS proposals (
    id               BIGSERIAL PRIMARY KEY,
    kind             TEXT NOT NULL,                -- skill | doc | new_doc
    kb_id            TEXT NOT NULL DEFAULT '',     -- 知识库 id（kind 为 doc / new_doc 时）
    target           TEXT NOT NULL,                -- 技能 id 或文档名
    dept_id          TEXT NOT NULL,                -- 目标所属部门（all = 全公司），决定谁来审核
    proposer         TEXT NOT NULL,
    proposer_name    TEXT NOT NULL DEFAULT '',
    proposer_dept    TEXT NOT NULL DEFAULT '',
    summary          TEXT NOT NULL,
    rationale        TEXT NOT NULL DEFAULT '',
    evidence         TEXT NOT NULL DEFAULT '',
    trace_id         TEXT NOT NULL DEFAULT '',
    proposed_content TEXT,
    base_version     INTEGER NOT NULL DEFAULT 0,   -- 提出建议时目标的版本
    status           TEXT NOT NULL DEFAULT 'open', -- open | accepted | rejected
    result_version   INTEGER,
    reviewer         TEXT NOT NULL DEFAULT '',
    review_note      TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at      TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS proposals_one_open ON proposals (proposer, kind, kb_id, target) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS proposals_status ON proposals (status, created_at DESC);

-- 工作成果：应用 / agent 通过 report_work 上报「做成了什么」，看板据此展示产出与进度
CREATE TABLE IF NOT EXISTS work_items (
    id           BIGSERIAL PRIMARY KEY,
    org          TEXT NOT NULL,
    user_name    TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    dept         TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT '其他',
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT '已完成',
    progress     INTEGER NOT NULL DEFAULT 100,
    link         TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    trace_id     TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS work_items_updated ON work_items (org, updated_at DESC);
-- 应用自动上报用的幂等键：同一个人、同一来源、同一个 key 只有一条，重复上报是更新
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS ext_key TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS work_items_ext ON work_items (org, user_name, source, ext_key) WHERE ext_key <> '';

-- 应用健康：员工电脑上安装 / 登录 / 打开应用 / 运行的结果（成功也记），只保留 7 天，见 health.py
CREATE TABLE IF NOT EXISTS app_health_events (
    id                BIGSERIAL PRIMARY KEY,
    org               TEXT NOT NULL,
    user_name         TEXT NOT NULL,
    display_name      TEXT NOT NULL DEFAULT '',
    dept              TEXT NOT NULL DEFAULT '',
    device_id         TEXT NOT NULL DEFAULT '',
    app_id            TEXT NOT NULL DEFAULT '',
    app_version       TEXT NOT NULL DEFAULT '',
    stage             TEXT NOT NULL,
    ok                BOOLEAN NOT NULL,
    code              TEXT NOT NULL,
    message           TEXT NOT NULL DEFAULT '',
    os                TEXT NOT NULL DEFAULT '',
    os_version        TEXT NOT NULL DEFAULT '',
    arch              TEXT NOT NULL DEFAULT '',
    agent             TEXT NOT NULL DEFAULT '',
    agent_version     TEXT NOT NULL DEFAULT '',
    connector_version TEXT NOT NULL DEFAULT '',
    at                TIMESTAMPTZ NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_health_at ON app_health_events (org, at DESC);
"""

PACK_FIELDS = ("name", "dept", "status", "description", "skills", "knowledge_bases", "tools", "models",
               "monthly_quota", "max_action_level", "external_access", "model_mode", "gpu_quota_minutes", "apps")
PACK_DEFAULTS = {"model_mode": "中枢模型", "gpu_quota_minutes": 0, "apps": []}
JSON_FIELDS = {"skills", "knowledge_bases", "tools", "models", "apps"}


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    if not settings.database_url:
        raise RuntimeError("未配置 HUB_DATABASE_URL")
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


def init_schema() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        if conn.execute("SELECT count(*) AS n FROM role_packs").fetchone()["n"] == 0:
            for rp in demo_seed.ROLE_PACKS:
                upsert_role_pack(rp["id"], rp, conn)


def _pack_row(row: dict) -> dict:
    out = dict(row)
    out.pop("updated_at", None)
    return out


def role_packs() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM role_packs ORDER BY CASE status WHEN '已上线' THEN 0 ELSE 1 END, id").fetchall()
    return [_pack_row(r) for r in rows]


def upsert_role_pack(pack_id: str, data: dict, conn: psycopg.Connection | None = None) -> None:
    data = {**PACK_DEFAULTS, **data}
    vals = {k: (Jsonb(data[k]) if k in JSON_FIELDS else data[k]) for k in PACK_FIELDS}
    cols = ", ".join(PACK_FIELDS)
    params = ", ".join(f"%({k})s" for k in PACK_FIELDS)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in PACK_FIELDS)
    sql = (f"INSERT INTO role_packs (id, {cols}) VALUES (%(id)s, {params}) "
           f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now()")
    if conn is not None:
        conn.execute(sql, {"id": pack_id, **vals})
    else:
        with connect() as c:
            c.execute(sql, {"id": pack_id, **vals})


def assignments(org: str) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT user_name, role_pack_id FROM role_assignments WHERE org = %s", (org,)).fetchall()
    return {r["user_name"]: r["role_pack_id"] for r in rows}


def assign(org: str, user_name: str, role_pack_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO role_assignments (org, user_name, role_pack_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (org, user_name) DO UPDATE SET role_pack_id = EXCLUDED.role_pack_id, updated_at = now()",
            (org, user_name, role_pack_id),
        )


def add_audit(**event) -> None:
    keys = ("trace_id", "org", "user_name", "display_name", "dept", "channel", "kind", "tool",
            "detail", "result", "tokens", "model", "cost", "summary")
    row = {k: event.get(k) for k in keys}
    row["tokens"] = row["tokens"] or 0
    row["cost"] = row["cost"] or 0
    for k in ("display_name", "dept", "detail", "summary"):
        row[k] = row[k] or ""
    with connect() as conn:
        conn.execute(
            f"INSERT INTO audit_events ({', '.join(keys)}) VALUES ({', '.join(f'%({k})s' for k in keys)})", row)


def recent_audit(org: str, days: int = 7) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM audit_events WHERE org = %s AND ts > now() - make_interval(days => %s) ORDER BY ts",
            (org, days),
        ).fetchall()


def traces_from_events(events: list[dict], dept_names: dict[str, str]) -> list[dict]:
    """把审计事件按 trace_id 聚合成控制台使用的链路结构（与演示数据结构相同）。"""
    grouped: dict[str, list[dict]] = {}
    for e in events:
        grouped.setdefault(e["trace_id"], []).append(e)
    traces = []
    for tid, rows in grouped.items():
        first = rows[0]
        steps = [{
            "time": _iso(r["ts"]), "kind": r["kind"], "tool": r["tool"], "detail": r["detail"],
            "result": r["result"], "tokens": r["tokens"], "model": r["model"], "cost": float(r["cost"]),
        } for r in rows]
        outcome = "被拦截" if any(s["result"] == "拒绝" for s in steps) else (
            "待审批" if any(s["result"] == "待确认" for s in steps) else "成功")
        summary = next((r["summary"] for r in rows if r["summary"]), "") or steps[0]["detail"]
        traces.append({
            "id": tid, "member_id": first["user_name"], "member": first["display_name"] or first["user_name"],
            "dept": first["dept"], "dept_name": dept_names.get(first["dept"], first["dept"] or "未分配部门"),
            "channel": first["channel"], "started_at": steps[0]["time"], "summary": summary, "outcome": outcome,
            "tokens": sum(s["tokens"] for s in steps), "cost": round(sum(s["cost"] for s in steps), 4), "steps": steps,
        })
    traces.sort(key=lambda t: t["started_at"], reverse=True)
    return traces


MODEL_TAIL_SECONDS = 600  # 最后一步工具调用之后，模型还要组织回答，留出这段时间归入同一链路


def attach_model_calls(traces: list[dict], logs: list[dict], org: str, usd_cny: float,
                       official_channel: str = "官方 agent", quota_of=None) -> None:
    """把 New API 的模型调用日志并入链路的步骤。

    归属分两层：
    1. 精确：Hermes 会话用的 key 名带追踪 ID（hub-<组织>-<用户>~<追踪 ID>），日志的 token_name 直接指明属于哪条链路；
       指向的链路不存在（太旧、已出统计窗口）时丢弃，绝不按时间窗硬塞给别的链路
    2. 估算：基础 key 的调用看不到追踪 ID，按「同一员工 + 链路时间窗」归属——从链路第一步开始，到该员工下一条链路
       开始（或最后一步之后 MODEL_TAIL_SECONDS 秒）为止
    只处理官方 agent 入口——外部智能体不走员工的模型 key。
    """
    from .newapi import trace_from_token_name, user_from_token_name

    def add_step(t: dict, log: dict) -> None:
        tokens = int(log.get("prompt_tokens") or 0) + int(log.get("completion_tokens") or 0)
        model = log.get("model_name") or "unknown"
        t["steps"].append({
            "time": datetime.fromtimestamp(log.get("created_at") or 0).astimezone().replace(microsecond=0).isoformat(),
            "kind": "模型", "tool": "llm.chat", "result": "通过", "tokens": tokens, "model": model,
            "detail": f"调用模型 {model}（输入 {log.get('prompt_tokens') or 0} / 输出 {log.get('completion_tokens') or 0} tokens）",
            # New API 的额度单位：500000 = 1 美元；quota_of 可以按当前价格重算（记录里的额度在价格没设好时会虚高）
            "cost": (quota_of(log) if quota_of else (log.get("quota") or 0)) / 500000 * usd_cny,
        })

    by_id = {t["id"]: t for t in traces if t["channel"] == official_channel}
    by_user: dict[str, list[dict]] = {}
    for log in logs:
        name = log.get("token_name") or ""
        user = user_from_token_name(name, org)
        if not user:
            continue
        trace_id = trace_from_token_name(name)
        if trace_id:
            if trace_id in by_id and by_id[trace_id]["member_id"] == user:
                add_step(by_id[trace_id], log)
            continue
        by_user.setdefault(user, []).append(log)

    mine: dict[str, list[dict]] = {}
    for t in by_id.values():
        if t["member_id"] in by_user:
            mine.setdefault(t["member_id"], []).append(t)
    for user, ts in mine.items():
        ts.sort(key=lambda t: t["steps"][0]["time"])
        for i, t in enumerate(ts):
            start = datetime.fromisoformat(t["steps"][0]["time"]).timestamp()
            end = datetime.fromisoformat(t["steps"][-1]["time"]).timestamp() + MODEL_TAIL_SECONDS
            if i + 1 < len(ts):
                end = min(end, datetime.fromisoformat(ts[i + 1]["steps"][0]["time"]).timestamp())
            for log in by_user[user]:
                if start <= (log.get("created_at") or 0) < end:
                    add_step(t, log)
    for t in by_id.values():
        t["steps"].sort(key=lambda s: s["time"])
        t["tokens"] = sum(s["tokens"] for s in t["steps"])
        t["cost"] = round(sum(s["cost"] for s in t["steps"]), 4)


def _iso(ts: datetime) -> str:
    return ts.astimezone().replace(microsecond=0).isoformat()



# ---- GPU 节点与任务 ----

def sync_gpu_nodes(nodes: list[dict]) -> None:
    with connect() as conn:
        ids = [n["id"] for n in nodes]
        for n in nodes:
            conn.execute(
                "INSERT INTO gpu_nodes (id, name, url, gpu) VALUES (%(id)s, %(name)s, %(url)s, %(gpu)s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, gpu = EXCLUDED.gpu", n)
        conn.execute("DELETE FROM gpu_nodes WHERE NOT (id = ANY(%s))", (ids,))


def gpu_nodes() -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_nodes ORDER BY id").fetchall()


def update_node_status(node_id: str, online: bool, vram_total: int = 0, vram_free: int = 0) -> None:
    with connect() as conn:
        conn.execute("UPDATE gpu_nodes SET online = %s, vram_total = %s, vram_free = %s, "
                     "last_seen = CASE WHEN %s THEN now() ELSE last_seen END WHERE id = %s",
                     (online, vram_total, vram_free, online, node_id))


# 不在本机 ComfyUI 节点上跑的任务（由调度服务的远程分支处理）：第三方出图 API 与 H3 网关各排各的队
API_WORKFLOWS = ("api-image",)
H3_WORKFLOWS = ("h3-image", "h3-video")
REMOTE_WORKFLOWS = API_WORKFLOWS + H3_WORKFLOWS


def create_gpu_task(task: dict) -> None:
    keys = ("id", "trace_id", "org", "user_name", "display_name", "dept", "channel", "workflow", "params")
    row = {k: task.get(k, "") for k in keys} | {"params": Jsonb(task.get("params") or {})}
    with connect() as conn:
        conn.execute(f"INSERT INTO gpu_tasks ({', '.join(keys)}) VALUES ({', '.join(f'%({k})s' for k in keys)})", row)


def gpu_task(task_id: str) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_tasks WHERE id = %s", (task_id,)).fetchone()


def gpu_seconds_this_month(org: str, user_name: str) -> float:
    """本月这个人占用 GPU 的秒数：已结束的按实际时长，正在跑的算到现在。"""
    with connect() as conn:
        return float(conn.execute(
            "SELECT coalesce(sum(extract(epoch FROM coalesce(finished_at, now()) - started_at)), 0) AS s FROM gpu_tasks "
            "WHERE org = %s AND user_name = %s AND workflow <> 'api-image' AND started_at >= date_trunc('month', now())", (org, user_name)).fetchone()["s"])


def gpu_tasks_since(org: str, days: int) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_tasks WHERE org = %s AND created_at > now() - make_interval(days => %s)",
                            (org, days)).fetchall()


def pending_task_count(org: str, user_name: str) -> int:
    with connect() as conn:
        return conn.execute("SELECT count(*) AS n FROM gpu_tasks WHERE org = %s AND user_name = %s "
                            "AND status IN ('queued', 'running')", (org, user_name)).fetchone()["n"]


def queue_position(task_id: str) -> int:
    """这个排队任务前面还有几个：先提交的排队任务，加上正在生成的任务（它们占着节点，必须先跑完）。"""
    with connect() as conn:
        return conn.execute(
            "SELECT count(*) FILTER (WHERE g.status = 'queued' AND g.created_at < t.created_at) "
            "     + count(*) FILTER (WHERE g.status = 'running') AS n "
            "FROM gpu_tasks g, (SELECT created_at, workflow FROM gpu_tasks WHERE id = %(id)s) t "
            "WHERE (CASE WHEN g.workflow = ANY(%(api)s) THEN 'api' WHEN g.workflow = ANY(%(h3)s) THEN 'h3' ELSE 'gpu' END) = "
            "      (CASE WHEN t.workflow = ANY(%(api)s) THEN 'api' WHEN t.workflow = ANY(%(h3)s) THEN 'h3' ELSE 'gpu' END)",
            {"id": task_id, "api": list(API_WORKFLOWS), "h3": list(H3_WORKFLOWS)}).fetchone()["n"]  # 本机 GPU、第三方 API、H3 网关各排各的队


def claim_task_for(node_id: str) -> dict | None:
    """把最早的排队任务分给空闲节点（多个调度进程并发时用 SKIP LOCKED 保证不重复领取）。"""
    with connect() as conn:
        busy = conn.execute("SELECT 1 FROM gpu_tasks WHERE status = 'running' AND node_id = %s", (node_id,)).fetchone()
        if busy:
            return None
        return conn.execute(
            "UPDATE gpu_tasks SET status = 'running', node_id = %s, started_at = now() WHERE id = ("
            "  SELECT id FROM gpu_tasks WHERE status = 'queued' AND workflow <> ALL(%s) "
            "  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ") RETURNING *", (node_id, list(REMOTE_WORKFLOWS))).fetchone()


def touch_presence(org: str, user_name: str, client: str | None = None, version: str | None = None,
                   os: str | None = None) -> None:
    """刷新在线时间；没带的字段保留上次的值（MCP 调用只知道人，不知道用的是哪个 agent）。"""
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_presence (org, user_name, client, version, os) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (org, user_name) DO UPDATE SET last_seen = now(), "
            "client = coalesce(EXCLUDED.client, agent_presence.client), "
            "version = coalesce(EXCLUDED.version, agent_presence.version), os = coalesce(EXCLUDED.os, agent_presence.os)",
            (org, user_name, client or None, version or None, os or None))
        # 按天记「今天在线过」，总览的在线趋势据此统计（每人每天一行，重复报到不增加）
        conn.execute("INSERT INTO agent_presence_daily (org, day, user_name) VALUES (%s, CURRENT_DATE, %s) "
                     "ON CONFLICT DO NOTHING", (org, user_name))


def touch_presence_at(org: str, user_name: str, ts) -> None:
    """用一个已发生的时间点刷新在线时间（模型网关里的最近一次调用）：只往后推，不会把更新的时间改旧；不动 client / version / os。"""
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_presence (org, user_name, last_seen) VALUES (%s, %s, %s) "
            "ON CONFLICT (org, user_name) DO UPDATE SET last_seen = GREATEST(agent_presence.last_seen, EXCLUDED.last_seen)",
            (org, user_name, ts))
        conn.execute("INSERT INTO agent_presence_daily (org, day, user_name) VALUES (%s, (%s::timestamptz)::date, %s) "
                     "ON CONFLICT DO NOTHING", (org, ts, user_name))


def online_by_day(org: str, days: int) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT day::text AS d, count(*) AS n FROM agent_presence_daily "
                            "WHERE org = %s AND day > CURRENT_DATE - %s GROUP BY day", (org, days)).fetchall()
    return {r["d"]: r["n"] for r in rows}


def denied_by_day(org: str, days: int) -> dict[str, int]:
    """每天被中枢拦截的次数（审计里结果为「拒绝」的事件）。"""
    with connect() as conn:
        rows = conn.execute("SELECT (ts AT TIME ZONE 'Asia/Shanghai')::date::text AS d, count(*) AS n FROM audit_events "
                            "WHERE org = %s AND result = '拒绝' AND ts > now() - make_interval(days => %s) GROUP BY 1",
                            (org, days + 1)).fetchall()
    return {r["d"]: r["n"] for r in rows}


def last_event_by_user(org: str) -> dict[str, datetime]:
    """每个员工在审计里最近一条事件的时间（成员列表的「最近活跃」用）。"""
    with connect() as conn:
        rows = conn.execute("SELECT user_name, max(ts) AS ts FROM audit_events WHERE org = %s GROUP BY user_name", (org,)).fetchall()
    return {r["user_name"]: r["ts"] for r in rows if r["user_name"]}


def presence_rows(org: str) -> dict[str, dict]:
    with connect() as conn:
        return {r["user_name"]: r for r in conn.execute("SELECT * FROM agent_presence WHERE org = %s", (org,)).fetchall()}


def requeue_gpu_task(task_id: str) -> None:
    """把卡住的任务放回队列（保持原来的排队顺序），记一次重试。"""
    with connect() as conn:
        conn.execute("UPDATE gpu_tasks SET status = 'queued', node_id = NULL, prompt_id = NULL, started_at = NULL, "
                     "attempts = attempts + 1 WHERE id = %s AND status = 'running'", (task_id,))


def running_tasks() -> list[dict]:
    """正在本机 GPU 节点上跑的任务（第三方 API / H3 网关的任务不在其中，见 running_api_tasks）。"""
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_tasks WHERE status = 'running' AND workflow <> ALL(%s) "
                            "ORDER BY started_at", (list(REMOTE_WORKFLOWS),)).fetchall()


def running_api_tasks(workflows: tuple[str, ...] = API_WORKFLOWS) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_tasks WHERE status = 'running' AND workflow = ANY(%s) "
                            "ORDER BY started_at", (list(workflows),)).fetchall()


def claim_api_tasks(limit: int, workflows: tuple[str, ...] = API_WORKFLOWS, node_id: str = "api") -> list[dict]:
    """把排队中的远程任务（第三方 API 或 H3 网关）置为运行中，同时进行的总数不超过 limit（多个调度进程并发时用 SKIP LOCKED）。"""
    with connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM gpu_tasks WHERE status = 'running' AND workflow = ANY(%s)",
                         (list(workflows),)).fetchone()["n"]
        if n >= limit:
            return []
        return conn.execute(
            "UPDATE gpu_tasks SET status = 'running', node_id = %s, started_at = now() WHERE id IN ("
            "  SELECT id FROM gpu_tasks WHERE status = 'queued' AND workflow = ANY(%s) "
            "  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s) RETURNING *", (node_id, list(workflows), limit - n)).fetchall()


def update_gpu_task(task_id: str, **fields) -> None:
    for k in ("images", "params"):
        if k in fields:
            fields[k] = Jsonb(fields[k])
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    if fields.get("status") in ("done", "failed"):
        sets += ", finished_at = now()"
    with connect() as conn:
        conn.execute(f"UPDATE gpu_tasks SET {sets} WHERE id = %(id)s", {**fields, "id": task_id})


def recent_gpu_tasks(limit: int = 100) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_tasks ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()


def gpu_task_stats() -> dict[str, dict]:
    """每个节点今天完成的任务数、正在跑的任务数，以及全局排队数。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT node_id, count(*) FILTER (WHERE status = 'done' AND finished_at::date = now()::date) AS done_today, "
            "count(*) FILTER (WHERE status = 'running') AS running FROM gpu_tasks WHERE node_id IS NOT NULL GROUP BY node_id"
        ).fetchall()
        queued = conn.execute("SELECT count(*) AS n FROM gpu_tasks WHERE status = 'queued'").fetchone()["n"]
    return {r["node_id"]: dict(r) for r in rows} | {"_queued": {"n": queued}}


# ---- 工作成果 ----
WORK_KEYS = ("org", "user_name", "display_name", "dept", "kind", "title", "status", "progress", "link", "note", "source", "trace_id", "ext_key")


def add_work_item(item: dict) -> int:
    row = {k: item.get(k, "" if k not in ("progress",) else 0) for k in WORK_KEYS}
    with connect() as conn:
        return conn.execute(
            f"INSERT INTO work_items ({', '.join(WORK_KEYS)}) VALUES ({', '.join(f'%({k})s' for k in WORK_KEYS)}) RETURNING id", row
        ).fetchone()["id"]


def upsert_work_item(item: dict) -> int:
    """按 (org, user_name, source, ext_key) 幂等写入：已有就更新内容，没有就新建。"""
    row = {k: item.get(k, "" if k != "progress" else 0) for k in WORK_KEYS}
    cols = ("kind", "title", "status", "progress", "link", "note", "trace_id")
    with connect() as conn:
        return conn.execute(
            f"INSERT INTO work_items ({', '.join(WORK_KEYS)}) VALUES ({', '.join(f'%({k})s' for k in WORK_KEYS)}) "
            "ON CONFLICT (org, user_name, source, ext_key) WHERE ext_key <> '' DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols) + ", display_name = EXCLUDED.display_name, dept = EXCLUDED.dept, updated_at = now() "
            "RETURNING id", row).fetchone()["id"]


def update_work_item(item_id: int, org: str, user_name: str, fields: dict) -> bool:
    """只能改自己的条目；返回是否改到了。"""
    allowed = {k: v for k, v in fields.items() if k in ("kind", "title", "status", "progress", "link", "note", "trace_id") and v is not None}
    sets = ", ".join(f"{k} = %({k})s" for k in allowed)
    with connect() as conn:
        cur = conn.execute(f"UPDATE work_items SET {sets}{', ' if sets else ''}updated_at = now() "
                           "WHERE id = %(id)s AND org = %(org)s AND user_name = %(u)s",
                           {**allowed, "id": item_id, "org": org, "u": user_name})
        return cur.rowcount > 0


def work_items_since(org: str, since: datetime, user_name: str | None = None) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM work_items WHERE org = %s AND updated_at >= %s AND (%s::text IS NULL OR user_name = %s) "
            "ORDER BY updated_at DESC", (org, since, user_name, user_name)).fetchall()


# ---- 控制台角色与部门配置 ----
def console_roles(org: str) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT user_name, role, dept_id FROM console_roles WHERE org = %s ORDER BY role, dept_id, user_name", (org,)).fetchall()


def roles_of(org: str, user_name: str) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT role, dept_id FROM console_roles WHERE org = %s AND user_name = %s", (org, user_name)).fetchall()


def set_dept_managers(org: str, dept_id: str, users: list[str]) -> None:
    """整体替换某个部门的主管名单。"""
    with connect() as conn:
        conn.execute("DELETE FROM console_roles WHERE org = %s AND role = 'manager' AND dept_id = %s", (org, dept_id))
        for u in dict.fromkeys(users):
            conn.execute("INSERT INTO console_roles (org, user_name, role, dept_id) VALUES (%s, %s, 'manager', %s)", (org, u, dept_id))


def set_bosses(org: str, users: list[str]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM console_roles WHERE org = %s AND role = 'boss'", (org,))
        for u in dict.fromkeys(users):
            conn.execute("INSERT INTO console_roles (org, user_name, role, dept_id) VALUES (%s, %s, 'boss', '')", (org, u))


def drop_user_roles(org: str, user_name: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM console_roles WHERE org = %s AND user_name = %s", (org, user_name))


def dept_defaults(org: str) -> dict[str, str]:
    with connect() as conn:
        return {r["dept_id"]: r["role_pack_id"] for r in conn.execute("SELECT dept_id, role_pack_id FROM dept_config WHERE org = %s", (org,)).fetchall()}


def set_dept_default(org: str, dept_id: str, role_pack_id: str | None) -> None:
    with connect() as conn:
        if role_pack_id:
            conn.execute("INSERT INTO dept_config (org, dept_id, role_pack_id) VALUES (%s, %s, %s) "
                         "ON CONFLICT (org, dept_id) DO UPDATE SET role_pack_id = EXCLUDED.role_pack_id", (org, dept_id, role_pack_id))
        else:
            conn.execute("DELETE FROM dept_config WHERE org = %s AND dept_id = %s", (org, dept_id))


# ---------------- 应用健康 ----------------

HEALTH_COLS = ("org", "user_name", "display_name", "dept", "device_id", "app_id", "app_version", "stage", "ok", "code", "message",
               "os", "os_version", "arch", "agent", "agent_version", "connector_version", "at")


def add_health_events(org: str, user_name: str, display_name: str, dept: str, events: list[dict], keep_days: int) -> int:
    """写入一批已清洗的事件，顺手删掉超过保留天数的旧事件。"""
    rows = [{**e, "org": org, "user_name": user_name, "display_name": display_name, "dept": dept} for e in events]
    with connect() as conn:
        if rows:
            with conn.cursor() as cur:
                cur.executemany(f"INSERT INTO app_health_events ({', '.join(HEALTH_COLS)}) VALUES ({', '.join(f'%({k})s' for k in HEALTH_COLS)})", rows)
        conn.execute("DELETE FROM app_health_events WHERE at < now() - make_interval(days => %s)", (keep_days,))
    return len(rows)


def health_events(org: str, days: int, app_id: str | None = None, app_version: str | None = None,
                  user_name: str | None = None, device_id: str | None = None, limit: int = 20000) -> list[dict]:
    """最近 days 天的事件，按时间倒序。按应用筛选时，接入器自身的事件（安装、登录，app_id 为空）也一并返回。"""
    sql = "SELECT * FROM app_health_events WHERE org = %s AND at > now() - make_interval(days => %s)"
    args: list = [org, days]
    if app_id:
        sql += " AND (app_id = %s OR app_id = '')"
        args.append(app_id)
    if app_version:
        sql += " AND (app_version = %s OR app_id = '')"
        args.append(app_version)
    if user_name:
        sql += " AND user_name = %s"
        args.append(user_name)
    if device_id is not None:
        sql += " AND device_id = %s"
        args.append(device_id)
    sql += " ORDER BY at DESC, id DESC LIMIT %s"
    args.append(limit)
    with connect() as conn:
        return conn.execute(sql, args).fetchall()
