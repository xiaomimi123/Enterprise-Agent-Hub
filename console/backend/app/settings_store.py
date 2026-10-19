"""中枢设置的键值存储（数据库 hub_settings 表）：出图通道开关、出图 API 列表等管理员在页面上改的配置。"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from . import db


def get(key: str, default=None):
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM hub_settings WHERE key = %s", (key,)).fetchone()
    return default if row is None else row["value"]


def put(key: str, value) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO hub_settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", (key, Jsonb(value)))
