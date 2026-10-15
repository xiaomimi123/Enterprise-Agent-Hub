"""中枢模型代理：员工的每次模型调用经过中枢，进入审计链路。

员工的 agent 不直连模型网关（New API），base_url 指向中枢的 /v1：
中枢按 key 识别员工 → 原样转发给 New API（模型白名单、月额度、按人计量仍由网关执行）→
把每次调用（模型、token 数、trace_id）写进审计事件。
「登录 → 查询 → 出图 → 花了多少 token」由此串在一条链路里（启动计划第 5 步）。

- 身份：Bearer key 是员工专属的 New API key，发放时已登记 key → 员工 的映射（db.model_keys）
- 追踪：员工端 agent 注入 X-Hub-Trace-Id 请求头（hub_agent 生成的配置带 default_headers），
  同一会话的模型调用与 MCP 调用共用一个 trace；没有该头时每次调用单独一条
- 金额：审计里记 token 数；花费金额以 New API 的计量为准（控制台「用量与成本」页展示）
- 直连封堵：New API 端口只对中枢开放（compose 里绑回环地址），绕过中枢的调用无法认证
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import db
from .config import settings

log = logging.getLogger("hub.model_proxy")

router = APIRouter()

# 中枢 → 模型网关。对话可能很长（生图描述、长文写作），读超时放宽到 10 分钟
_TIMEOUT = httpx.Timeout(connect=10, read=600, write=120, pool=600)
_HTTP: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
    return _HTTP


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _owner(request: Request) -> dict | None:
    key = _bearer(request)
    return db.model_key_owner(key) if key else None


def _trace(request: Request) -> str:
    return request.headers.get("x-hub-trace-id") or f"llm-{uuid.uuid4().hex[:12]}"


def _error(message: str, status: int) -> JSONResponse:
    """OpenAI 格式的错误，员工端 agent 直接显示 message。"""
    return JSONResponse(status_code=status,
                        content={"error": {"message": message, "type": "invalid_request_error"}})


def _audit(owner: dict, trace_id: str, model: str, prompt: int, completion: int, result: str, detail: str) -> None:
    try:
        db.add_audit(trace_id=trace_id, org=owner["org"], user_name=owner["user_name"],
                     display_name=owner["display_name"] or owner["user_name"], dept=owner["dept"],
                     channel=owner["channel"] or "官方 agent", kind="模型", tool="model.chat",
                     detail=detail, result=result, tokens=(prompt or 0) + (completion or 0),
                     model=model or None, cost=0)
    except Exception:  # noqa: BLE001 审计写不进去不该影响模型调用本身
        log.exception("模型调用审计写入失败")


def _excerpt(body: bytes) -> str:
    """取最后一条用户消息的开头一段，让审计里看得出「问了什么」。太大或解析不了就放弃。"""
    if not body or len(body) > 2_000_000:
        return ""
    try:
        data = json.loads(body)
        messages = data.get("messages") or []
    except (ValueError, AttributeError):
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        c = msg.get("content")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        text = " ".join(str(c or "").split())
        return text[:80] + ("…" if len(text) > 80 else "")
    return ""


def _error_message(body: bytes) -> str:
    """模型网关错误响应里的人话（OpenAI 格式 error.message，或 New API 的 message 字段）。"""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return ""
    if isinstance(data, dict):
        err = data.get("error")
        msg = err.get("message") if isinstance(err, dict) else (data.get("message") if err is None else None)
        if isinstance(msg, str) and msg:
            return " ".join(msg.split())[:150]
    return ""


def _sse_tail(tail: bytes) -> tuple[int, int, str]:
    """从流式响应的末尾解析出（输入 tokens、输出 tokens、模型名）：最后一个带 usage 的 data 块，
    模型名取第一个能解析出来的 data 块。"""
    prompt = completion = 0
    model = ""
    for line in tail.splitlines():
        if not line.startswith(b"data:"):
            continue
        try:
            data = json.loads(line[5:].strip())
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        usage = data.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or prompt)
        completion = int(usage.get("completion_tokens") or completion)
        model = model or data.get("model") or ""
    return prompt, completion, model


def _json_usage(data: dict) -> tuple[int, int]:
    usage = data.get("usage") or {}
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


@router.get("/v1/models")
async def list_models(request: Request):
    """模型列表（OpenAI 兼容）。只是元数据，不记审计。"""
    if _owner(request) is None:
        return _error("无效的模型 key，请重新同步员工端配置（hub_agent.py sync）", 401)
    try:
        r = await _client().get(f"{settings.newapi_endpoint}/v1/models",
                                headers={"Authorization": request.headers["authorization"]})
    except httpx.HTTPError as e:
        raise RuntimeError(f"模型网关不可达：{e}") from e
    return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    owner = _owner(request)
    if owner is None:
        return _error("无效的模型 key，请重新同步员工端配置（hub_agent.py sync）", 401)
    body = await request.body()
    fwd = {"Authorization": request.headers["authorization"], "Content-Type": "application/json"}
    try:
        req = _client().build_request("POST", f"{settings.newapi_endpoint}/v1/chat/completions",
                                      content=body, headers=fwd)
        upstream = await _client().send(req, stream=True)
    except httpx.HTTPError as e:
        _audit(owner, _trace(request), "", 0, 0, "拒绝", f"模型网关不可达：{e}")
        return _error("模型网关暂时不可用，请稍后再试", 502)

    trace_id = _trace(request)
    asked = _excerpt(body)
    prefix = f"，问了「{asked}」" if asked else ""

    # 错误与普通 JSON 响应：整包读完再转发（流式响应见下面的分支）
    if "text/event-stream" not in upstream.headers.get("content-type", ""):
        try:
            content = await upstream.aread()
        finally:
            status, content_type = upstream.status_code, upstream.headers.get("content-type")
            await upstream.aclose()
        prompt = completion = 0
        model = ""
        if status < 400:
            try:
                data = json.loads(content)
                prompt, completion = _json_usage(data)
                model = data.get("model") or ""
            except (ValueError, UnicodeDecodeError):
                pass
            _audit(owner, trace_id, model, prompt, completion, "通过",
                   f"对话模型 {model or '未知'}：输入 {prompt} / 输出 {completion} tokens{prefix}")
        else:
            msg = _error_message(content) or f"HTTP {status}"
            _audit(owner, trace_id, model, 0, 0, "拒绝", f"模型网关拒绝：{msg}{prefix}")
        return Response(content=content, status_code=status, media_type=content_type)

    async def passthrough() -> AsyncGenerator[bytes, None]:
        """流式转发：原样把字节推给员工端，留一份末尾用于解析 usage 和模型名。"""
        tail = b""
        try:
            async for chunk in upstream.aiter_bytes():
                tail = (tail + chunk)[-262144:]
                yield chunk
        finally:
            await upstream.aclose()
            if upstream.status_code < 400:
                prompt, completion, model = _sse_tail(tail)
                _audit(owner, trace_id, model, prompt, completion, "通过",
                       f"对话模型 {model or '未知'}：输入 {prompt} / 输出 {completion} tokens{prefix}")
            else:
                _audit(owner, trace_id, "", 0, 0, "拒绝",
                       f"模型网关拒绝：{_error_message(tail) or f'HTTP {upstream.status_code}'}{prefix}")

    return StreamingResponse(passthrough(), status_code=upstream.status_code,
                             media_type=upstream.headers.get("content-type"))
