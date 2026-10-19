"""open_app 的权限与凭证：岗位包 apps 里有这个应用才发凭证，成功与拒绝都写审计。"""

from __future__ import annotations

from . import apps, db, policy


class AppDenied(Exception):
    """没有权限或应用不存在，消息可以直接给员工看。"""


def _audit(**event) -> None:
    db.add_audit(**event)


def _record(p: policy.Principal, trace_id: str, detail: str, result: str) -> None:
    _audit(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
           channel=p.channel, kind="拦截" if result == "拒绝" else "应用", tool="app.open", detail=detail, result=result)


def ticket_for(p: policy.Principal, trace_id: str, app_id: str) -> dict:
    a = apps.get_app(app_id)
    if a is None:
        _record(p, trace_id, f"申请打开应用「{app_id}」：中枢没有这个应用", "拒绝")
        raise AppDenied(f"中枢没有这个应用：{app_id}。可用 list_apps 查看你能打开的应用。")
    if p.is_external or a.id not in (p.pack.get("apps") or []):
        why = "外部智能体不能打开应用" if p.is_external else f"岗位包「{p.pack.get('name', '')}」没有打开「{a.name}」的权限"
        _record(p, trace_id, f"申请打开应用「{a.name}」：{why}", "拒绝")
        raise AppDenied(f"{why}。该请求已记录。")
    _record(p, trace_id, f"打开应用「{a.name}」v{a.version}", "通过")
    return {"app_id": a.id, "name": a.name, "version": a.version, "sha256": apps.sha256_of(a.zip_path),
            "download_url": apps.signed_zip_url(a), "entry": a.entry, "requires": a.requires, "start_args": a.start_args}


def list_for(p: policy.Principal) -> list[dict]:
    if p.is_external:
        return []
    allowed = set(p.pack.get("apps") or [])
    return [{"id": a.id, "name": a.name, "version": a.version, "description": a.description}
            for a in apps.list_apps() if a.id in allowed]
