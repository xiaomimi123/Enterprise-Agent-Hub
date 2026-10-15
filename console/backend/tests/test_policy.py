from app import policy
from app.demo_seed import ROLE_PACKS

PACKS = {p["id"]: p for p in ROLE_PACKS}


def principal(pack_id: str, channel: str = policy.OFFICIAL) -> policy.Principal:
    return policy.Principal(org="xinghe", user_name="u", display_name="u", dept="ops", channel=channel, pack=PACKS[pack_id])


def test_official_agent_gets_all_pack_kbs():
    p = principal("rp-xhs-ops")
    assert set(policy.allowed_kbs(p)) == set(PACKS["rp-xhs-ops"]["knowledge_bases"])
    assert "kb-finance" not in policy.allowed_kbs(p)


def test_external_agent_only_reads_kbs_open_to_external():
    p = principal("rp-xhs-ops", policy.EXTERNAL)
    kbs = policy.allowed_kbs(p)
    assert "kb-brand" in kbs and "kb-xhs-hits" not in kbs
    assert "未开放给外部智能体" in policy.explain_kb_denial(p, "kb-xhs-hits")


def test_external_access_closed_blocks_everything():
    p = principal("rp-finance", policy.EXTERNAL)
    assert policy.allowed_kbs(p) == []
    assert "不允许外部智能体接入" in policy.explain_kb_denial(p, "kb-finance")


def test_denial_reason_names_the_pack():
    p = principal("rp-xhs-ops")
    assert "小红书运营" in policy.explain_kb_denial(p, "kb-finance")
    assert not policy.can_use_tool(p, "erp.finance")


def test_dept_from_groups():
    assert policy.dept_from_groups(["xinghe/ops"]) == "ops"
    assert policy.dept_from_groups([]) == ""
