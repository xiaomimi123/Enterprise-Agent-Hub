import pytest

from app import auth, skillstore as ss

ADMIN = {"role": "admin", "depts": None}
BOSS = {"role": "boss", "depts": None}
OPS_MANAGER = {"role": "manager", "depts": ["ops"]}
NOBODY = {"role": None, "depts": []}


@pytest.mark.parametrize("scope,dept,expected", [
    (ADMIN, "ops", "direct"), (ADMIN, "all", "direct"), (BOSS, "hr", "direct"), (BOSS, "all", "direct"),
    (OPS_MANAGER, "ops", "direct"),          # 本部门：直接生效
    (OPS_MANAGER, "all", "review"),          # 全公司：提交审核
    (OPS_MANAGER, "hr", None),               # 别的部门：不能改
    (NOBODY, "ops", None),
])
def test_who_can_edit_what(scope, dept, expected):
    assert ss.plan_for(scope, dept) == expected


def test_only_boss_and_admin_review():
    assert ss.can_review(ADMIN) and ss.can_review(BOSS) and not ss.can_review(OPS_MANAGER)


GOOD = "---\nname: 选题策划\ndescription: 产出一周选题表\n---\n\n# 选题策划\n步骤 1\n"


def test_content_validation():
    text, meta = ss.clean_content(GOOD.replace("\n", "\r\n"))
    assert "\r" not in text and meta["name"] == "选题策划" and text.endswith("\n")
    for bad in ["", "没有 frontmatter\n正文", "---\nname: x\n---\n正文", "---\ndescription: y\n---\n正文", "---\nname: x\ndescription: y\n---\n   \n"]:
        with pytest.raises(ss.SkillError):
            ss.clean_content(bad)
    with pytest.raises(ss.SkillError):
        ss.clean_content(GOOD + "x" * (ss.MAX_BYTES + 1))


def test_skill_id_rules(monkeypatch):
    for bad in ["", "A", "x", "has space", "带中文", "-lead", "a" * 60]:
        with pytest.raises(ss.SkillError):
            ss.create(bad, "ops", ADMIN, {"name": "a"}, GOOD)


def test_manager_write_routes_are_allowlisted_but_review_is_boss_only():
    def allowed(role, method, path):
        return any(method == m and rx.match(path) for m, rx in auth.ROLE_ALLOWED[role])
    for method, path in [("PUT", "/api/skills/xhs-topic"), ("POST", "/api/skills"), ("POST", "/api/skills/xhs-topic/rollback"), ("GET", "/api/skills/xhs-topic/history"), ("GET", "/api/skill-reviews")]:
        assert allowed("manager", method, path) and allowed("boss", method, path)
    assert not allowed("manager", "POST", "/api/skill-reviews/xhs-topic/3") and allowed("boss", "POST", "/api/skill-reviews/xhs-topic/3")
    assert not allowed("manager", "DELETE", "/api/skills/xhs-topic") and not allowed("boss", "PATCH", "/api/skills/xhs-topic")
