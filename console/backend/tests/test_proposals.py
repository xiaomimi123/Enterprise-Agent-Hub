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
