# 001 · 阶段 0 自研轻量 MCP Server

- 日期：2026-10-15
- 状态：已采纳

## 背景
中枢需要以 MCP Server 的形式向员工端暴露 tool，并在中枢层强制执行权限。可选方案：直接用现成 MCP 网关（IBM ContextForge、Obot、Docker MCP Gateway），或者自己写。

## 决定
阶段 0 用 Python 自己写一个轻量 MCP Server，暂不引入现成网关。

## 理由
- 现成网关的 RBAC 管的是「能调哪个 tool」，管不了「同一个查询 tool 返回哪些部门的数据」。按部门过滤知识，无论用不用网关都得在自己的 Server 里实现。
- 阶段 0 只有 3–4 个 tool，自己写比学习和改造现成网关更快。
- 审计 trace ID 需要从令牌校验一直贯通到 RAGFlow 查询和 ComfyUI 任务，自己写最容易打通。
- Python 和 RAGFlow、ComfyUI 的 SDK 衔接顺手。

## 后果与复审条件
- 鉴权、tool 过滤、日志都要自己维护。
- 当 tool 数量明显增多，或需要接入大量第三方 MCP server 时，再评估要不要在自研 Server 前面加一层现成网关。
