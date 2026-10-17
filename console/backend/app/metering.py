"""中枢资源计量：不管员工用哪种 agent（Hermes、WorkBuddy、Cursor……），只统计经过中枢的东西。

- 工具调用：审计里「通过」的检索、技能、生成派发（登录、被拒绝的、调度服务的完成记录都不算）
- GPU：生成任务的实际运行时长（开始到结束），以及出图张数、视频条数
模型 token 不在这里：用中枢模型的由 New API 按人计量，用 agent 自带模型的由那家产品自己计费。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

TOOL_KINDS = {"检索", "技能", "工具"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".gif"}


def gpu_seconds(task: dict) -> float:
    if not task.get("started_at") or not task.get("finished_at"):
        return 0.0
    return max(0.0, (task["finished_at"] - task["started_at"]).total_seconds())


def hub_usage(events: list[dict], tasks: list[dict], members: dict[str, dict], packs: dict[str, dict]) -> dict:
    per = defaultdict(lambda: {"tool_calls": 0, "images": 0, "videos": 0, "seconds": 0.0})
    for e in events:
        if e["kind"] in TOOL_KINDS and e["result"] == "通过":
            per[e["user_name"]]["tool_calls"] += 1
    for t in tasks:
        u = per[t["user_name"]]
        u["seconds"] += gpu_seconds(t)
        if t["status"] == "done":
            for name in t["images"]:
                u["videos" if Path(name).suffix.lower() in VIDEO_SUFFIXES else "images"] += 1

    by_member = []
    for uid, v in per.items():
        m = members.get(uid, {})
        pack = packs.get(m.get("role_pack"), {})
        by_member.append({
            "member_id": uid, "member": m.get("name", uid), "dept_name": m.get("dept_name", "未分配部门"),
            "role_pack": pack.get("name", ""), "model_mode": pack.get("model_mode", "中枢模型"),
            "tool_calls": v["tool_calls"], "images": v["images"], "videos": v["videos"],
            "gpu_minutes": round(v["seconds"] / 60, 1), "gpu_quota_minutes": int(pack.get("gpu_quota_minutes") or 0),
        })
    by_member.sort(key=lambda x: (x["gpu_minutes"], x["tool_calls"]), reverse=True)

    dept = defaultdict(lambda: {"tool_calls": 0, "gpu_minutes": 0.0})
    for m in by_member:
        dept[m["dept_name"]]["tool_calls"] += m["tool_calls"]
        dept[m["dept_name"]]["gpu_minutes"] += m["gpu_minutes"]
    by_dept = sorted(({"dept": k, "tool_calls": v["tool_calls"], "gpu_minutes": round(v["gpu_minutes"], 1)}
                      for k, v in dept.items()), key=lambda x: (x["gpu_minutes"], x["tool_calls"]), reverse=True)
    return {
        "totals": {"tool_calls": sum(m["tool_calls"] for m in by_member), "images": sum(m["images"] for m in by_member),
                   "videos": sum(m["videos"] for m in by_member),
                   "gpu_minutes": round(sum(v["seconds"] for v in per.values()) / 60, 1)},
        "by_member": by_member,
        "by_dept": by_dept,
    }
