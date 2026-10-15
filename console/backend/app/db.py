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
"""

PACK_FIELDS = ("name", "dept", "status", "description", "skills", "knowledge_bases", "tools", "models",
               "monthly_quota", "max_action_level", "external_access")
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


def _iso(ts: datetime) -> str:
    return ts.astimezone().replace(microsecond=0).isoformat()

