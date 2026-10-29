"""控制台「应用健康」：员工电脑上安装、登录、打开应用、运行的成功率和常见报错。只有管理员能看（老板 / 主管的白名单里没有这个接口）。

数据见 health.py；演示模式没有数据库，返回空数据。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from . import db, health, presence, rollout
from .config import settings

router = APIRouter(tags=["health"])


def _names() -> dict[str, str]:
    from .main import provider  # 延迟导入：main 导入了本模块
    try:
        return {m.get("id"): m.get("name", "") for m in provider.members()}
    except Exception:  # noqa: BLE001 拿不到成员名单就用事件里记的名字
        return {}


def latest_connector() -> str:
    """中枢正在发布给大家的接入器版本：有灰度配置时是 stable，否则是 agent/hub_agent.py 里的 VERSION。
    旧版标记据此判断；灰度中的 candidate 不算「最新」，免得没升级的人都被标成旧版。"""
    return rollout.stable_version(settings.agent_dir)


@router.get("/health/summary")
def summary(days: int = Query(7, ge=1, le=health.RETENTION_DAYS), app_id: str | None = None, app_version: str | None = None):
    if not settings.database_url:  # 演示模式：示例数据
        rows = health.demo_rows()
        demo_names = {r["user_name"]: r["display_name"] for r in rows} | {"sunqi": "孙七", "zhouba": "周八"}
        data = health.merge_presence(health.summarize(rows, demo_names), health.demo_presence(), latest_connector(), demo_names, days)
        return {**data, "apps": [("xhs-workbench", "0.7.9")], "days": days}
    rows = db.health_events(settings.casdoor_org, days, app_id=app_id or None, app_version=app_version or None)
    names = _names()
    presence.sync_from_gateway(settings.casdoor_org)   # 和总览 / 成员页同一套在线判断
    data = health.merge_presence(health.summarize(rows, names), db.presence_rows(settings.casdoor_org), latest_connector(), names, days)
    data["apps"] = sorted({(r["app_id"], r["app_version"]) for r in rows if r["app_id"]}, reverse=True)
    data["days"] = days
    return data


@router.get("/health/device")
def device(user_name: str, device_id: str = "", days: int = Query(7, ge=1, le=health.RETENTION_DAYS)):
    """某人某台设备的事件时间线（最近 200 条）。"""
    if not settings.database_url:
        rows = [r for r in health.demo_rows() if r["user_name"] == user_name and r["device_id"] == device_id]
    else:
        rows = db.health_events(settings.casdoor_org, days, user_name=user_name, device_id=device_id, limit=200)
    return {"events": [{**{k: r[k] for k in ("stage", "ok", "code", "message", "app_id", "app_version", "agent", "agent_version", "os", "at")},
                        "stage_label": health.STAGES.get(r["stage"], r["stage"]),
                        "label": health.CODES.get(r["code"], health.CODES["UNKNOWN"])[0],
                        "fix": health.CODES.get(r["code"], health.CODES["UNKNOWN"])[1]} for r in rows]}
