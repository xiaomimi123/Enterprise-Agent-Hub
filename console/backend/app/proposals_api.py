"""控制台「改进建议」：审核员工的 agent 提交的技能 / 知识库修改建议。规则见 proposals.py。

路由挂在 /api 下，经过 auth.console_user（白名单：管理员、老板、部门主管）；具体能不能处理某一条由 proposals.can_handle 判断。
采纳 = 用建议的内容（或审核人改过的内容）生成新版本并发布，知识库文档发布后同步到 RAGFlow。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, kbmeta, kbstore, proposals, skillstore
from .config import settings
from .content import KB_REGISTRY
from .ragflow import from_settings
from .skillstore import Conflict, SkillError

router = APIRouter(tags=["proposals"])


def _need_db() -> None:
    if not settings.database_url:
        raise HTTPException(400, "演示模式不支持改进建议")


def _audit(user: dict, tool: str, detail: str) -> None:
    db.add_audit(trace_id="", org=user.get("org") or "", user_name=user.get("name") or "", display_name=user.get("display_name") or "",
                 dept="", channel="控制台", kind="配置", tool=tool, detail=detail, result="通过")


def _dept_name(dept: str) -> str:
    from .main import provider  # 延迟导入：main 导入了本模块
    return "全公司" if dept == skillstore.ALL else provider.d["dept_names"].get(dept, dept)


def _run(fn):
    try:
        return fn()
    except Conflict as e:
        raise HTTPException(409, str(e)) from None
    except SkillError as e:
        raise HTTPException(400, str(e)) from None


def _target_name(row: dict) -> str:
    if row["kind"] == "skill":
        s = skillstore.get_skill(row["target"])
        return f"{s['name']}（{row['target']}）" if s else row["target"]
    return row["target"]


def _summary(row: dict) -> dict:
    cur_text, cur_version = proposals.current(row)
    return {"id": row["id"], "kind": row["kind"], "kb_id": row["kb_id"], "kb_name": KB_REGISTRY.get(row["kb_id"], {}).get("name", ""),
            "target": row["target"], "target_name": _target_name(row), "dept": row["dept_id"], "dept_name": _dept_name(row["dept_id"]),
            "proposer": row["proposer"], "proposer_name": row["proposer_name"], "summary": row["summary"], "status": row["status"],
            "has_content": bool(row["proposed_content"]), "created_at": row["created_at"].isoformat(),
            "stale": row["kind"] != "new_doc" and row["status"] == "open" and row["base_version"] != cur_version,
            "review_note": row["review_note"], "reviewer": row["reviewer"]}


@router.get("/proposals")
def list_proposals(status: str = "open", user: dict = Depends(auth.console_user)):
    _need_db()
    kbmeta.refresh()
    return [_summary(r) for r in proposals.list_for(user, status)]


def _own(proposal_id: int, user: dict) -> dict:
    row = proposals.get(proposal_id)
    if row is None or not proposals.can_handle(user, row["dept_id"]):
        raise HTTPException(404, "建议不存在")
    return row


@router.get("/proposals/{proposal_id}")
def proposal(proposal_id: int, user: dict = Depends(auth.console_user)):
    _need_db()
    row = _own(proposal_id, user)
    cur_text, cur_version = proposals.current(row)
    return {**_summary(row), "rationale": row["rationale"], "evidence": row["evidence"], "trace_id": row["trace_id"],
            "proposed_content": row["proposed_content"] or "", "current_content": cur_text, "current_version": cur_version,
            "base_version": row["base_version"], "result_version": row["result_version"]}


class AcceptBody(BaseModel):
    content: str | None = None  # 审核人改过的内容；不传就用建议里的
    note: str = ""
    confirm_stale: bool = False


class RejectBody(BaseModel):
    note: str


@router.post("/proposals/{proposal_id}/accept")
def accept(proposal_id: int, body: AcceptBody, user: dict = Depends(auth.console_user)):
    _need_db()
    row = _own(proposal_id, user)
    r = _run(lambda: proposals.accept(proposal_id, user, user, body.content, body.note, body.confirm_stale))
    r["synced"] = None
    client = from_settings()
    if row["kind"] != "skill" and client is not None:
        r["synced"] = kbstore.sync_doc(client, row["kb_id"], row["target"])
    _audit(user, "proposal.accept", f"采纳 {row['proposer_name']} 的建议 #{proposal_id}（{row['kind']}：{row['target']}）→ 第 {r['version']} 版，已生效")
    return r


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: int, body: RejectBody, user: dict = Depends(auth.console_user)):
    _need_db()
    row = _own(proposal_id, user)
    r = _run(lambda: proposals.reject(proposal_id, user, user, body.note))
    _audit(user, "proposal.reject", f"驳回 {row['proposer_name']} 的建议 #{proposal_id}（{row['kind']}：{row['target']}）")
    return r
