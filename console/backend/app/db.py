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
-- 容错：任务被改派过几次（节点掉线 / 超时后重新排队）
ALTER TABLE gpu_tasks ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
"""

PACK_FIELDS = ("name", "dept", "status", "description", "skills", "knowledge_bases", "tools", "models",
               "monthly_quota", "max_action_level", "external_access", "model_mode", "gpu_quota_minutes")
PACK_DEFAULTS = {"model_mode": "中枢模型", "gpu_quota_minutes": 0}
JSON_FIELDS = {"skills", "knowledge_bases", "tools", "models"}


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
                       official_channel: str = "官方 agent") -> None:
    """把 New API 的模型调用日志按「同一员工 + 链路时间窗」并入链路的步骤。

    模型网关只认员工的 key，看不到追踪 ID，所以用时间窗归属：从链路第一步开始，到该员工下一条链路开始
    （或最后一步之后 MODEL_TAIL_SECONDS 秒）为止。只处理官方 agent 入口——外部智能体不走员工的模型 key。
    """
    from .newapi import user_from_token_name

    by_user: dict[str, list[dict]] = {}
    for log in logs:
        user = user_from_token_name(log.get("token_name") or "", org)
        if user:
            by_user.setdefault(user, []).append(log)
    mine: dict[str, list[dict]] = {}
    for t in traces:
        if t["channel"] == official_channel and t["member_id"] in by_user:
            mine.setdefault(t["member_id"], []).append(t)
    for user, ts in mine.items():
        ts.sort(key=lambda t: t["steps"][0]["time"])
        for i, t in enumerate(ts):
            start = datetime.fromisoformat(t["steps"][0]["time"]).timestamp()
            end = datetime.fromisoformat(t["steps"][-1]["time"]).timestamp() + MODEL_TAIL_SECONDS
            if i + 1 < len(ts):
                end = min(end, datetime.fromisoformat(ts[i + 1]["steps"][0]["time"]).timestamp())
            for log in by_user[user]:
                at = log.get("created_at") or 0
                if not start <= at < end:
                    continue
                tokens = int(log.get("prompt_tokens") or 0) + int(log.get("completion_tokens") or 0)
                model = log.get("model_name") or "unknown"
                t["steps"].append({
                    "time": datetime.fromtimestamp(at).astimezone().replace(microsecond=0).isoformat(),
                    "kind": "模型", "tool": "llm.chat", "result": "通过", "tokens": tokens, "model": model,
                    "detail": f"调用模型 {model}（输入 {log.get('prompt_tokens') or 0} / 输出 {log.get('completion_tokens') or 0} tokens）",
                    # New API 的额度单位：500000 = 1 美元
                    "cost": (log.get("quota") or 0) / 500000 * usd_cny,
                })
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
            "WHERE org = %s AND user_name = %s AND started_at >= date_trunc('month', now())", (org, user_name)).fetchone()["s"])


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
            "FROM gpu_tasks g, (SELECT created_at FROM gpu_tasks WHERE id = %s) t", (task_id,)).fetchone()["n"]


def claim_task_for(node_id: str) -> dict | None:
    """把最早的排队任务分给空闲节点（多个调度进程并发时用 SKIP LOCKED 保证不重复领取）。"""
    with connect() as conn:
        busy = conn.execute("SELECT 1 FROM gpu_tasks WHERE status = 'running' AND node_id = %s", (node_id,)).fetchone()
        if busy:
            return None
        return conn.execute(
            "UPDATE gpu_tasks SET status = 'running', node_id = %s, started_at = now() WHERE id = ("
            "  SELECT id FROM gpu_tasks WHERE status = 'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ") RETURNING *", (node_id,)).fetchone()


def requeue_gpu_task(task_id: str) -> None:
    """把卡住的任务放回队列（保持原来的排队顺序），记一次重试。"""
    with connect() as conn:
        conn.execute("UPDATE gpu_tasks SET status = 'queued', node_id = NULL, prompt_id = NULL, started_at = NULL, "
                     "attempts = attempts + 1 WHERE id = %s AND status = 'running'", (task_id,))


def running_tasks() -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM gpu_tasks WHERE status = 'running' ORDER BY started_at").fetchall()


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
