"""开发用的模拟大模型（OpenAI 兼容接口），只在演示/开发环境部署。

它不是真的模型，而是一个「剧本」：根据员工的问题决定调用中枢 MCP 的哪个工具，拿到工具结果后再组织回答。
这样不花钱也能把整条链路跑通：员工 → Hermes → New API（按人计量）→ 本服务 → Hermes 调用中枢 MCP（权限与审计）。

运行：uvicorn app.mock_llm:app --port 8300
"""

from __future__ import annotations

import json
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL = "hub-mock"

# 问题里出现这些词时，指定检索对应的知识库（用来演示越权拦截）
KB_HINTS = {
    "财务": "财务制度与报表", "报表": "财务制度与报表", "报销": "财务制度与报表",
    "薪酬": "人事制度与薪酬", "工资": "人事制度与薪酬",
    "违禁": "违禁词与广告法", "广告法": "违禁词与广告法",
    "爆款": "历史爆款笔记", "人设": "品牌调性与人设",
}

app = FastAPI(title="模拟大模型（开发用）")


def _tokens(text: str) -> int:
    """粗略估算 token 数，用于让 New API 记录用量。"""
    return max(1, len(text) // 2)


def _text_of(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""


def _unwrap(text: str) -> str:
    """去掉 agent 给工具结果加的防注入包装（如 Hermes 的 <untrusted_tool_result>），取出原始结果。"""
    m = re.search(r"<untrusted_tool_result[^>]*>(.*?)(?:</untrusted_tool_result>|$)", text, re.S)
    if not m:
        return text.strip()
    lines = m.group(1).strip().splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("[", "{")) or "无权" in line or "没有找到" in line or "不存在" in line:
            return "\n".join(lines[i:]).strip()
    return lines[-1].strip() if lines else ""


def _find_tool(tools: list[dict], suffix: str) -> str | None:
    """在请求带来的工具列表里找中枢 MCP 的工具（不同 agent 会加不同前缀，按后缀匹配）。"""
    for t in tools:
        name = (t.get("function") or {}).get("name", "")
        if name == suffix or name.endswith("_" + suffix) or name.endswith("__" + suffix) or name.endswith("." + suffix):
            return name
    return None


def _plan(messages: list[dict], tools: list[dict]) -> tuple[str | None, dict | None, str]:
    """返回（工具名, 参数, 文本）。有工具调用时文本为空。"""
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":
        result = _unwrap(_text_of(last))
        # 有的 agent 会把 MCP 结果再包一层 {"result": "..."}
        try:
            wrapped = json.loads(result)
            if isinstance(wrapped, dict) and isinstance(wrapped.get("result"), str):
                result = wrapped["result"]
        except ValueError:
            pass
        if result.startswith("无权") or "无权" in result[:30]:
            return None, None, f"中枢拒绝了这次请求：{result}\n\n这是公司的权限策略，我无法绕过。如果工作确实需要，请联系管理员调整你的岗位包。"
        try:
            data = json.loads(result)
        except ValueError:
            data = None
        if isinstance(data, list) and data and isinstance(data[0], dict) and "knowledge_base" in data[0]:
            lines = [f"- 【{d['knowledge_base']} · {d['document']}】{d['text'][:80]}" for d in data[:3]]
            return None, None, "根据中枢知识库检索到的内容：\n" + "\n".join(lines)
        if isinstance(data, dict) and "role_pack" in data:
            return None, None, (f"你是{data['name']}，当前岗位包是「{data['role_pack']}」，"
                                f"可用知识库：{'、'.join(data.get('knowledge_bases', []))}。")
        if isinstance(data, list) and data and isinstance(data[0], dict) and "description" in data[0]:
            return None, None, "你可以使用这些技能：\n" + "\n".join(f"- {s['name']}：{s['description']}" for s in data)
        return None, None, "中枢返回：" + result[:300]

    question = next((_text_of(m) for m in reversed(messages) if m.get("role") == "user"), "")
    if re.search(r"我是谁|身份|岗位包", question) and (name := _find_tool(tools, "whoami")):
        return name, {}, ""
    if "技能" in question and (name := _find_tool(tools, "list_skills")):
        return name, {}, ""
    if name := _find_tool(tools, "search_knowledge"):
        args: dict = {"query": question[:100]}
        for word, kb in KB_HINTS.items():
            if word in question:
                args["knowledge_base"] = kb
                break
        return name, args, ""
    return None, None, f"（模拟模型）收到：{question[:100]}。当前没有连接中枢的工具。"


def _completion(tool: str | None, args: dict | None, text: str, prompt_tokens: int) -> dict:
    msg: dict = {"role": "assistant", "content": text or None}
    finish = "stop"
    if tool:
        msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                              "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]
        finish = "tool_calls"
    completion_tokens = _tokens(text or json.dumps(args or {}))
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}", "object": "chat.completion", "created": int(time.time()),
        "model": MODEL, "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


def _stream(body: dict):
    """把一次完整回复拆成 SSE 流式片段（OpenAI chat.completion.chunk 格式）。"""
    choice = body["choices"][0]
    base = {"id": body["id"], "object": "chat.completion.chunk", "created": body["created"], "model": MODEL}
    msg = choice["message"]
    yield {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}
    if msg.get("tool_calls"):
        tc = msg["tool_calls"][0]
        yield {**base, "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": tc["id"], "type": "function",
            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}]}, "finish_reason": None}]}
    else:
        text = msg.get("content") or ""
        for i in range(0, len(text), 24):
            yield {**base, "choices": [{"index": 0, "delta": {"content": text[i:i + 24]}, "finish_reason": None}]}
    yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}],
           "usage": body["usage"]}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "hub-dev"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    req = await request.json()
    messages = req.get("messages") or []
    tools = req.get("tools") or []
    # 开发用：打印收到的工具名，便于排查 agent 是否把中枢工具交给了模型
    print(f"[mock-llm] {len(messages)} 条消息，工具：{[(t.get('function') or {}).get('name') for t in tools]}", flush=True)
    tool, args, text = _plan(messages, tools)
    body = _completion(tool, args, text, _tokens(json.dumps(messages, ensure_ascii=False)))
    if not req.get("stream"):
        return JSONResponse(body)

    def sse():
        for chunk in _stream(body):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
