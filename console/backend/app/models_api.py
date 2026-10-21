"""控制台「模型」页的接口：对话模型上游与出图通道。挂在 /api 下，已经限定为管理员。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, h3gateway, imageapi, model_upstreams
from .config import settings
from .model_upstreams import UpstreamError
from .newapi import DEFAULT_MODEL_RATIO, USD_PER_M_AT_RATIO_1, NewApi, NewApiError

router = APIRouter(prefix="/models", tags=["models"])
NEW_API_DEFAULT_INPUT = DEFAULT_MODEL_RATIO * USD_PER_M_AT_RATIO_1


def make_newapi() -> NewApi:
    return NewApi()


def _audit(user: dict, tool: str, detail: str, result: str = "通过") -> None:
    """配置类操作的审计。详情里不得出现密钥。"""
    if not settings.database_url:
        return  # 演示模式没有数据库
    db.add_audit(trace_id="", org=user.get("org") or "", user_name=user.get("name") or "",
                 display_name=user.get("display_name") or "", dept="", channel="控制台", kind="配置", tool=tool,
                 detail=detail, result=result)


def gateway() -> NewApi:
    na = make_newapi()
    if not na.configured:
        raise HTTPException(503, "未配置模型网关（NEWAPI_ENDPOINT / NEWAPI_ACCESS_TOKEN / NEWAPI_ADMIN_ID）")
    return na


def _guard(fn):
    try:
        return fn()
    except UpstreamError as e:
        raise HTTPException(400, str(e)) from None
    except NewApiError as e:
        raise HTTPException(502, f"模型网关出错：{e}") from None


class PriceBody(BaseModel):
    input_per_m: float
    output_per_m: float | None = None


@router.get("/pricing")
def get_pricing(user: dict = Depends(auth.current_user)):
    """已开放模型的价格（美元 / 百万 token）。未设置价格的模型按 New API 默认的高倍率计费，费用虚高。"""
    na = gateway()
    rows = _guard(lambda: na.get_pricing(na.available_models()))
    return {"models": rows, "default_input_per_m": NEW_API_DEFAULT_INPUT, "usd_cny": settings.usd_cny}


@router.put("/pricing/{model}")
def set_pricing(model: str, body: PriceBody, user: dict = Depends(auth.current_user)):
    na = gateway()
    try:
        row = na.set_pricing(model, body.input_per_m, body.output_per_m)
    except NewApiError as e:
        raise HTTPException(400, str(e)) from None
    _audit(user, "model.pricing.set", f"设置模型价格「{row['model']}」：输入 ${row['input_per_m']:g}、输出 ${row['output_per_m']:g} / 百万 token")
    return row


@router.delete("/pricing/{model}")
def clear_pricing(model: str, user: dict = Depends(auth.current_user)):
    na = gateway()
    if not _guard(lambda: na.clear_pricing(model)):
        raise HTTPException(404, "这个模型没有自定义价格")
    _audit(user, "model.pricing.clear", f"清除模型价格「{model}」，恢复 New API 默认")
    return {"ok": True}


class ProbeBody(BaseModel):
    base_url: str
    key: str


class UpstreamBody(BaseModel):
    name: str
    base_url: str
    key: str
    models: list[str]


class UpstreamPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    key: str | None = None
    models: list[str] | None = None
    enabled: bool | None = None


@router.get("/upstreams")
def list_upstreams(na: NewApi = Depends(gateway)):
    return _guard(lambda: model_upstreams.list_upstreams(na))


@router.post("/upstreams/probe")
def probe_upstream(body: ProbeBody, na: NewApi = Depends(gateway)):
    return _guard(lambda: model_upstreams.probe(na, body.base_url, body.key))


@router.post("/upstreams")
def add_upstream(body: UpstreamBody, user: dict = Depends(auth.current_user), na: NewApi = Depends(gateway)):
    out = _guard(lambda: model_upstreams.add(na, body.name, body.base_url, body.key, body.models))
    _audit(user, "model.upstream.add", f"添加模型上游「{out['name']}」，开放 {len(out['models'])} 个模型")
    return out


@router.patch("/upstreams/{channel_id}")
def patch_upstream(channel_id: int, body: UpstreamPatch, user: dict = Depends(auth.current_user),
                   na: NewApi = Depends(gateway)):
    out = _guard(lambda: model_upstreams.patch(na, channel_id, name=body.name, base_url=body.base_url, key=body.key,
                                               models=body.models, enabled=body.enabled))
    if out is None:
        raise HTTPException(404, "没有这个上游")
    changed = [k for k, v in (("名称", body.name), ("地址", body.base_url), ("密钥", body.key or None),
                              ("开放的模型", body.models), ("启停", body.enabled)) if v is not None]
    _audit(user, "model.upstream.update", f"修改模型上游「{out['name']}」：{'、'.join(changed) or '无变化'}")
    return out


@router.delete("/upstreams/{channel_id}")
def delete_upstream(channel_id: int, user: dict = Depends(auth.current_user), na: NewApi = Depends(gateway)):
    found = next((u for u in _guard(lambda: model_upstreams.list_upstreams(na)) if u["id"] == channel_id), None)
    if found is None or not _guard(lambda: model_upstreams.remove(na, channel_id)):
        raise HTTPException(404, "没有这个上游")
    _audit(user, "model.upstream.delete", f"删除模型上游「{found['name']}」")
    return {"ok": True}


# ---- 出图通道 ----

class ProviderBody(BaseModel):
    name: str
    base_url: str
    model: str
    key: str
    params: dict | None = None


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    key: str | None = None
    params: dict | None = None
    enabled: bool | None = None


class RouteBody(BaseModel):
    route: str


ROUTE_TEXT = {"api": "第三方 API", "h3": "H3 网关", "gpu": "本机 GPU"}


class H3Body(BaseModel):
    base_url: str
    key: str | None = None
    enabled: bool | None = None
    verify_tls: bool | None = None


def _h3(fn):
    try:
        return fn()
    except h3gateway.H3Error as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:  # 密钥解密失败等
        raise HTTPException(500, str(e)) from None


def _img(fn):
    try:
        return fn()
    except imageapi.ImageApiError as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:  # 密钥解密失败等
        raise HTTPException(500, str(e)) from None


@router.get("/image")
def image_config():
    return {"route": imageapi.get_route(), "providers": imageapi.list_providers(),
            "video_route": h3gateway.get_video_route(), "h3": h3gateway.get_gateway()}


@router.post("/image/providers")
def add_image_provider(body: ProviderBody, user: dict = Depends(auth.current_user)):
    out = _img(lambda: imageapi.add_provider(body.name, body.base_url, body.model, body.key, body.params))
    _audit(user, "model.image.add", f"添加出图 API「{out['name']}」（模型 {out['model']}）")
    return out


@router.patch("/image/providers/{provider_id}")
def patch_image_provider(provider_id: str, body: ProviderPatch, user: dict = Depends(auth.current_user)):
    out = _img(lambda: imageapi.patch_provider(provider_id, name=body.name, base_url=body.base_url, model=body.model,
                                               key=body.key, params=body.params, enabled=body.enabled))
    if out is None:
        raise HTTPException(404, "没有这个出图 API")
    changed = [k for k, v in (("名称", body.name), ("地址", body.base_url), ("模型", body.model), ("密钥", body.key or None),
                              ("参数", body.params), ("启停", body.enabled)) if v is not None]
    _audit(user, "model.image.update", f"修改出图 API「{out['name']}」：{'、'.join(changed) or '无变化'}")
    return out


@router.delete("/image/providers/{provider_id}")
def delete_image_provider(provider_id: str, user: dict = Depends(auth.current_user)):
    found = next((p for p in imageapi.list_providers() if p["id"] == provider_id), None)
    if found is None or not imageapi.remove_provider(provider_id):
        raise HTTPException(404, "没有这个出图 API")
    _audit(user, "model.image.delete", f"删除出图 API「{found['name']}」")
    return {"ok": True}


@router.put("/image/route")
def set_image_route(body: RouteBody, user: dict = Depends(auth.current_user)):
    route = _img(lambda: imageapi.set_route(body.route))
    _audit(user, "model.image.route", f"出图通道切换为「{ROUTE_TEXT[route]}」")
    return {"route": route}


@router.post("/image/providers/{provider_id}/test")
def test_image_provider(provider_id: str, user: dict = Depends(auth.current_user)):
    c = _img(lambda: imageapi.provider_client(provider_id))
    if c is None:
        raise HTTPException(404, "没有这个出图 API")
    res = c.test()
    res["error"] = res["error"].replace(c.key, "••••")
    _audit(user, "model.image.test", f"测试出图 API：{'成功' if res['ok'] else '失败'}，耗时 {res['seconds']} 秒",
           "通过" if res["ok"] else "拒绝")
    return res


@router.put("/h3")
def save_h3(body: H3Body, user: dict = Depends(auth.current_user)):
    out = _h3(lambda: h3gateway.save_gateway(body.base_url, body.key, body.enabled, body.verify_tls))
    _audit(user, "model.h3.save", f"保存 H3 网关「{out['base_url']}」（{'启用' if out['enabled'] else '停用'}）")
    return out


@router.delete("/h3")
def delete_h3(user: dict = Depends(auth.current_user)):
    if not h3gateway.remove_gateway():
        raise HTTPException(404, "还没有配置 H3 网关")
    _audit(user, "model.h3.delete", "删除 H3 网关")
    return {"ok": True}


@router.put("/video/route")
def set_video_route(body: RouteBody, user: dict = Depends(auth.current_user)):
    route = _h3(lambda: h3gateway.set_video_route(body.route))
    _audit(user, "model.video.route", f"视频通道切换为「{ROUTE_TEXT[route]}」")
    return {"route": route}


@router.post("/h3/test")
def test_h3(user: dict = Depends(auth.current_user)):
    c = _h3(h3gateway.client)
    if c is None:
        raise HTTPException(404, "没有可用的 H3 网关")
    res = c.test()
    res["error"] = res["error"].replace(c.key, "••••")
    _audit(user, "model.h3.test", f"测试 H3 网关：{'成功' if res['ok'] else '失败'}，耗时 {res['seconds']} 秒",
           "通过" if res["ok"] else "拒绝")
    return res
