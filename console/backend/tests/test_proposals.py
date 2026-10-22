import pytest

from app import auth, policy, proposals as pr

ADMIN = {"role": "admin", "depts": None}
BOSS = {"role": "boss", "depts": None}
OPS = {"role": "manager", "depts": ["ops"]}
NOBODY = {"role": None, "depts": []}


@pytest.mark.parametrize("scope,dept,expected", [
    (ADMIN, "ops", True), (ADMIN, "all", True), (BOSS, "hr", True), (BOSS, "all", True),
    (OPS, "ops", True),            # 本部门内容的建议：主管处理
    (OPS, "all", False),           # 全公司内容：只有老板和管理员
    (OPS, "hr", False), (NOBODY, "ops", False),
])
def test_who_can_handle_a_proposal(scope, dept, expected):
    assert pr.can_handle(scope, dept) is expected


class P:
    user_name, display_name, dept, org, channel = "u", "U", "ops", "o", policy.OFFICIAL


def test_bad_requests_are_rejected_before_touching_anything():
    for kind, summary in [("rewrite", "x"), ("skill", ""), ("skill", "   ")]:
        with pytest.raises(pr.ProposalError):
            pr.create(P(), "t", kind, "xhs-topic", summary)


def test_content_rules():
    assert pr._clean_content("doc", None) is None and pr._clean_content("skill", "  ") is None
    with pytest.raises(pr.ProposalError):
        pr._clean_content("new_doc", None)                       # 新增文档必须带内容
    assert pr._clean_content("doc", "# t\n\n正文") == "# t\n\n正文\n"
    assert pr._clean_content("skill", "---\nname: a\ndescription: b\n---\n正文\n").startswith("---")
    with pytest.raises(Exception):
        pr._clean_content("skill", "没有 frontmatter")           # 技能建议要是合规的 SKILL.md


def allowed(role, method, path):
    return any(method == m and rx.match(path) for m, rx in auth.ROLE_ALLOWED[role])


def test_console_routes_are_allowlisted_for_boss_and_manager_only():
    for role in ("manager", "boss"):
        assert allowed(role, "GET", "/api/proposals") and allowed(role, "GET", "/api/proposals/12")
        assert allowed(role, "POST", "/api/proposals/12/accept") and allowed(role, "POST", "/api/proposals/12/reject")
        assert not allowed(role, "DELETE", "/api/proposals/12") and not allowed(role, "POST", "/api/proposals")
    assert not allowed("manager", "GET", "/api/proposals/abc")


def test_doc_name_with_slash_gives_a_clear_reason_instead_of_a_bare_tool_error():
    """回归：真实 CodeBuddy 提交的文档名含「/」（如「人群/场景」），KbError 没被捕获，agent 只看到「Error executing tool」，
    误以为是内容太长而改成了测试内容，留下一条垃圾建议。"""
    for kind in ("doc", "new_doc"):
        with pytest.raises(pr.ProposalError, match="文档名不合规"):
            pr.create(P(), "t", kind, "标题结构：数字 + 人群/场景", "summary", kb_id="kb-brand")


def test_mcp_tool_catches_every_validation_error():
    import inspect

    from app import mcp_server
    src = inspect.getsource(mcp_server.propose_improvement)
    assert "except SkillError" in src and "except proposals.ProposalError" not in src
