"""对话模型上游：管理员在控制台添加 / 停用 / 删除，真实数据在 New API 的渠道里，中枢不另存一份。

- 地址按 New API 的习惯保存为站点根（去掉末尾的 /v1：New API 请求时自己拼 /v1/chat/completions）
- 密钥只写不读：创建 / 修改时传给 New API，列表里只显示后四位（存在渠道的 remark 字段）
- 所有错误信息过滤掉密钥，不会回显给页面或写进审计
"""

from __future__ import annotations

from .newapi import NewApi, NewApiError
from .secretbox import mask_secret


class UpstreamError(Exception):
    """参数不合法或上游不可用，消息可以直接给管理员看（不含密钥）。"""


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")) or len(url) < 9:
        raise UpstreamError("地址必须以 http:// 或 https:// 开头")
    return url[:-3].rstrip("/") if url.endswith("/v1") else url


def _scrub(msg: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            msg = msg.replace(s, "••••")
    return msg


def _view(c: dict) -> dict:
    return {"id": c["id"], "name": c["name"], "base_url": c.get("base_url") or "",
            "models": [m for m in (c.get("models") or "").split(",") if m],
            "status": "enabled" if c.get("status") == 1 else "disabled", "key_hint": c.get("remark") or ""}


def list_upstreams(na: NewApi) -> list[dict]:
    return [_view(c) for c in na.list_channels()]


def probe(na: NewApi, base_url: str, key: str) -> dict:
    if not (key or "").strip():
        raise UpstreamError("请填写密钥")
    url = normalize_url(base_url)
    try:
        models = na.fetch_models(url, key.strip())
    except NewApiError as e:
        raise UpstreamError(f"连接上游失败：{_scrub(str(e), key)}") from None
    if not models:
        raise UpstreamError("连接成功，但上游没有返回任何模型")
    return {"models": models}


def add(na: NewApi, name: str, base_url: str, key: str, models: list[str]) -> dict:
    name, key = (name or "").strip(), (key or "").strip()
    if not name:
        raise UpstreamError("请填写名称")
    if not key:
        raise UpstreamError("请填写密钥")
    if not models:
        raise UpstreamError("请至少选择一个开放的模型")
    url = normalize_url(base_url)
    if any(c["name"] == name for c in na.list_channels()):
        raise UpstreamError(f"已经有叫「{name}」的上游，重名了")
    try:
        cid = na.create_channel(name, url, key, models, remark=mask_secret(key))
    except NewApiError as e:
        raise UpstreamError(_scrub(str(e), key)) from None
    return next(_view(c) for c in na.list_channels() if c["id"] == cid)


def _find(na: NewApi, channel_id: int) -> dict | None:
    return next((c for c in na.list_channels() if c["id"] == channel_id), None)


def patch(na: NewApi, channel_id: int, *, name: str | None = None, base_url: str | None = None, key: str | None = None,
          models: list[str] | None = None, enabled: bool | None = None) -> dict | None:
    """返回修改后的上游；不存在返回 None。key 为空（None 或空串）表示不改。"""
    if _find(na, channel_id) is None:
        return None
    fields: dict = {}
    if name is not None:
        if not name.strip():
            raise UpstreamError("请填写名称")
        fields["name"] = name.strip()
    if base_url is not None:
        fields["base_url"] = normalize_url(base_url)
    if models is not None:
        if not models:
            raise UpstreamError("请至少选择一个开放的模型")
        fields["models"] = ",".join(models)
    if enabled is not None:
        fields["status"] = 1 if enabled else 2
    key = (key or "").strip()
    if key:
        fields["key"], fields["remark"] = key, mask_secret(key)
    try:
        na.update_channel(channel_id, **fields)
    except NewApiError as e:
        raise UpstreamError(_scrub(str(e), key)) from None
    return _view(_find(na, channel_id))


def remove(na: NewApi, channel_id: int) -> bool:
    if _find(na, channel_id) is None:
        return False
    na.delete_channel(channel_id)
    return True
