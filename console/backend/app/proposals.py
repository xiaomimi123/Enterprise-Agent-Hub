"""改进建议：员工的 agent 对技能、知识库文档提出修改建议，人审核后才生效。

原则：agent 只能**提建议**，不能直接改；采纳由人决定，采纳后才通过现有的版本流程（skillstore / kbstore）产生新版本。
- 谁能提：能读到那个技能 / 知识库的员工（按岗位包），外部智能体不能；每人每天最多 DAILY_LIMIT 条，同一个人对同一目标同时只能有一条待处理的。
- 谁来审：本部门内容由该部门主管、老板、管理员；全公司内容只有老板和管理员（与技能库 / 知识库的审核规则一致）。
- 建议内容是不可信输入：只给人看（差异对比），从不自动执行或发布。
"""

from __future__ import annotations

from . import db, kbmeta, kbstore, roles, skillstore
from .content import KB_REGISTRY
from .skillstore import ALL, SkillError

DAILY_LIMIT = 10
KINDS = ("skill", "doc", "new_doc")
MAX_SUMMARY, MAX_RATIONALE, MAX_EVIDENCE = 200, 1000, 500


class ProposalError(SkillError):
    """参数不合法或没有权限，消息可以直接给用户（或 agent）看。"""


def can_handle(scope: dict, dept: str) -> bool:
    """能不能审核这个部门的建议：管理员 / 老板全部；主管只有自己的部门（全公司的不行）。"""
    if scope["role"] in (roles.ADMIN, roles.BOSS):
        return True
    return scope["role"] == roles.MANAGER and dept != ALL and dept in (scope["depts"] or [])


def _target_info(kind: str, kb_id: str, target: str) -> tuple[str, int]:
    """返回 (部门, 当前版本)；目标不存在就报错。"""
    if kind == "skill":
        row = skillstore.get_skill(target)
        if row is None or row["published_version"] <= 0:
            raise ProposalError(f"技能「{target}」不存在。")
        return row["dept_id"], row["published_version"]
    kbmeta.refresh()
    if kb_id not in KB_REGISTRY:
        raise ProposalError("知识库不存在。")
    dept = KB_REGISTRY[kb_id]["dept"]
    doc = kbstore.get_doc(kb_id, target)
    if kind == "doc":
        if doc is None or doc["deleted"] or doc["published_version"] <= 0:
            raise ProposalError(f"文档「{target}」不存在。要新增文档请用 new_doc。")
        return dept, doc["published_version"]
    if doc is not None and not doc["deleted"]:
        raise ProposalError(f"文档「{target}」已经存在，要修改请用 doc。")
    return dept, 0


def _clean_content(kind: str, content: str | None) -> str | None:
    if content is None or not content.strip():
        if kind == "new_doc":
            raise ProposalError("新增文档必须带上完整的文档内容（proposed_content）。")
        return None
    return skillstore.clean_content(content)[0] if kind == "skill" else kbstore.clean_content(content)


def create(p, trace_id: str, kind: str, target: str, summary: str, rationale: str = "", evidence: str = "", kb_id: str = "",
           proposed_content: str | None = None) -> dict:
    if kind not in KINDS:
        raise ProposalError("kind 只能是 skill（改技能）、doc（改文档）、new_doc（新增文档）。")
    summary = (summary or "").strip()
    if not summary:
        raise ProposalError("summary（一句话说明想改什么）不能为空。")
    target = (target or "").strip()
    if kind != "skill":
        target = kbstore.clean_name(target)
    dept, base = _target_info(kind, kb_id, target)
    try:
        content = _clean_content(kind, proposed_content)
    except SkillError as e:
        raise ProposalError(str(e)) from None
    with db.connect() as conn:
        used = conn.execute("SELECT count(*) AS n FROM proposals WHERE proposer = %s AND created_at >= date_trunc('day', now())", (p.user_name,)).fetchone()["n"]
        if used >= DAILY_LIMIT:
            raise ProposalError(f"今天已经提了 {DAILY_LIMIT} 条建议，明天再提。请优先提最重要的。")
        if conn.execute("SELECT 1 FROM proposals WHERE proposer = %s AND kind = %s AND kb_id = %s AND target = %s AND status = 'open'",
                        (p.user_name, kind, kb_id, target)).fetchone():
            raise ProposalError("你对这一项已经有一条待处理的建议，请等处理后再提。")
        row = conn.execute(
            "INSERT INTO proposals (kind, kb_id, target, dept_id, proposer, proposer_name, proposer_dept, summary, rationale, evidence, trace_id, proposed_content, base_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (kind, kb_id, target, dept, p.user_name, p.display_name, p.dept, summary[:MAX_SUMMARY], (rationale or "").strip()[:MAX_RATIONALE],
             (evidence or "").strip()[:MAX_EVIDENCE], trace_id, content, base)).fetchone()
    db.add_audit(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept, channel=p.channel, kind="建议",
                 tool="proposal.create", detail=f"[{kind}] {target}：{summary[:80]}", result="通过")
    return {"proposal_id": row["id"], "status": "open", "reviewer": "该部门主管" if dept != ALL else "老板或管理员"}


def mine(user_name: str, days: int = 30) -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT id, kind, kb_id, target, summary, status, review_note, created_at, reviewed_at FROM proposals "
                            "WHERE proposer = %s AND created_at > now() - make_interval(days => %s) ORDER BY created_at DESC", (user_name, days)).fetchall()


def get(proposal_id: int) -> dict | None:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM proposals WHERE id = %s", (proposal_id,)).fetchone()


def list_for(scope: dict, status: str = "open", limit: int = 100) -> list[dict]:
    """这个人能处理的建议（管理员 / 老板全部；主管只有自己部门的）。status：open / closed / all。"""
    cond = {"open": "status = 'open'", "closed": "status <> 'open'", "all": "true"}.get(status, "status = 'open'")
    with db.connect() as conn:
        rows = conn.execute(f"SELECT * FROM proposals WHERE {cond} ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return [r for r in rows if can_handle(scope, r["dept_id"])]


def current(row: dict) -> tuple[str, int]:
    """目标现在的内容和版本（技能 / 文档）；新增文档为空。"""
    if row["kind"] == "skill":
        r = skillstore.get_skill(row["target"])
        return (skillstore.read_skill(row["target"]) or ""), (r["published_version"] if r else 0)
    doc = kbstore.get_doc(row["kb_id"], row["target"])
    if doc is None or doc["deleted"]:
        return "", 0
    cur = next((v["content"] for v in kbstore.versions(row["kb_id"], row["target"], 1000) if v["version"] == doc["published_version"]), "")
    return cur, doc["published_version"]


def _close(proposal_id: int, status: str, user: dict, note: str, version: int | None) -> bool:
    with db.connect() as conn:
        n = conn.execute("UPDATE proposals SET status = %s, reviewer = %s, review_note = %s, result_version = %s, reviewed_at = now() "
                         "WHERE id = %s AND status = 'open'", (status, user["name"], (note or "").strip()[:200], version, proposal_id)).rowcount
    return n == 1


def reject(proposal_id: int, scope: dict, user: dict, note: str) -> dict:
    row = get(proposal_id)
    if row is None or row["status"] != "open":
        raise ProposalError("这条建议不存在，或已经处理过了。")
    if not can_handle(scope, row["dept_id"]):
        raise ProposalError("你没有处理这条建议的权限。")
    if not (note or "").strip():
        raise ProposalError("驳回要写一下原因（会反馈给提出建议的人）。")
    if not _close(proposal_id, "rejected", user, note, None):
        raise ProposalError("这条建议已经被别人处理了。")
    return {"status": "rejected"}


def accept(proposal_id: int, scope: dict, user: dict, content: str | None, note: str = "", confirm_stale: bool = False) -> dict:
    """采纳：用建议的内容（或审核人改过的内容）生成新版本并发布。返回 {version, published, kind, kb_id, target}。"""
    row = get(proposal_id)
    if row is None or row["status"] != "open":
        raise ProposalError("这条建议不存在，或已经处理过了。")
    if not can_handle(scope, row["dept_id"]):
        raise ProposalError("你没有处理这条建议的权限。")
    text = content if content is not None and content.strip() else row["proposed_content"]
    if not text:
        raise ProposalError("这条建议没有带新内容。请在编辑框里写好修改后的完整内容，再点采纳。")
    cur_text, cur_version = current(row)
    if row["kind"] != "new_doc" and row["base_version"] != cur_version and not confirm_stale:
        raise ProposalError(f"这条建议是基于第 {row['base_version']} 版提出的，目标现在已经是第 {cur_version} 版。请对照最新内容确认后，勾选「已确认」再采纳。")
    what = f"采纳 {row['proposer_name']} 的建议：{row['summary'][:60]}"
    if not _close(proposal_id, "accepted", user, note, None):  # 先占住，避免两个人同时采纳
        raise ProposalError("这条建议已经被别人处理了。")
    try:
        if row["kind"] == "skill":
            r = skillstore.save(row["target"], scope, user, text, what, base_version=None)
        elif row["kind"] == "doc":
            r = kbstore.save(row["kb_id"], row["target"], scope, user, text, what, base_version=None)
        else:
            r = kbstore.create(row["kb_id"], row["target"], scope, user, text, what)
    except Exception:
        with db.connect() as conn:  # 应用失败：恢复成待处理，让审核人修改后重试
            conn.execute("UPDATE proposals SET status = 'open', reviewer = '', review_note = '', reviewed_at = NULL WHERE id = %s", (proposal_id,))
        raise
    with db.connect() as conn:
        conn.execute("UPDATE proposals SET result_version = %s WHERE id = %s", (r["version"], proposal_id))
    _credit_proposer(row)
    return {**r, "published": r.get("status") == "published", "kind": row["kind"], "kb_id": row["kb_id"], "target": row["target"]}


def _credit_proposer(row: dict) -> None:
    """建议被采纳算提出人的一项成果，出现在工作看板里。"""
    try:
        db.upsert_work_item({"org": _org(), "user_name": row["proposer"], "display_name": row["proposer_name"], "dept": row["proposer_dept"], "kind": "改进建议",
                             "title": f"建议被采纳：{row['summary'][:80]}", "status": "已完成", "progress": 100, "source": "改进建议",
                             "trace_id": row["trace_id"], "ext_key": f"proposal:{row['id']}"})
    except Exception:  # noqa: BLE001 记成果失败不影响采纳
        pass


def _org() -> str:
    from .config import settings
    return settings.casdoor_org


def open_count(scope: dict) -> int:
    return len(list_for(scope, "open"))
