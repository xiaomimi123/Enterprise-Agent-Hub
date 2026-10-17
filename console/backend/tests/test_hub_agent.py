"""员工端接入器（agent/hub_agent.py）：岗位包技能同步到 WorkBuddy 的技能目录。"""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("hub_agent", Path(__file__).resolve().parents[3] / "agent" / "hub_agent.py")
hub_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hub_agent)

SKILL = "---\nname: 标题与正文撰写\ndescription: 按品牌人设写小红书标题和正文\n---\n\n# 标题与正文撰写\n步骤……\n"


def cfg(*ids):
    return {"employee": {"name": "周一诺", "role_pack": "小红书运营"},
            "skills": [{"id": i, "name": i, "description": f"{i} 的说明", "content": SKILL} for i in ids]}


@pytest.fixture
def wb(tmp_path):
    skills = tmp_path / ".workbuddy" / "skills"
    skills.mkdir(parents=True)
    (skills / "capcut").mkdir()                       # 员工自己装的技能
    (skills / "capcut" / "SKILL.md").write_text("mine", encoding="utf-8")
    (skills / "hub-mine").mkdir()                     # 前缀相同但不是中枢下发的（没有标记）
    (skills / "hub-mine" / "SKILL.md").write_text("mine too", encoding="utf-8")
    return skills


def test_writes_pack_skills_with_marker_and_banner(wb):
    n = hub_agent.sync_workbuddy_skills(cfg("xhs-writing", "xhs-cover"), wb)
    assert n == 2
    text = (wb / "hub-xhs-writing" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: 标题与正文撰写\n")          # frontmatter 仍在最前面，WorkBuddy 才能识别
    assert "enterprise-hub" in text and "小红书运营" in text      # 说明来源和调用方式
    assert (wb / "hub-xhs-writing" / hub_agent.WB_MARKER).exists()
    guide = (wb / "hub-guide" / "SKILL.md").read_text(encoding="utf-8")
    assert guide.startswith("---\n") and "search_knowledge" in guide and "周一诺" in guide


def test_resync_removes_revoked_skills_but_not_users_own(wb):
    hub_agent.sync_workbuddy_skills(cfg("xhs-writing", "xhs-cover"), wb)
    hub_agent.sync_workbuddy_skills(cfg("xhs-writing"), wb)      # 岗位包撤掉了 xhs-cover
    names = {p.name for p in wb.iterdir()}
    assert "hub-xhs-cover" not in names
    assert {"hub-xhs-writing", "hub-guide", "capcut", "hub-mine"} <= names
    assert (wb / "hub-mine" / "SKILL.md").read_text(encoding="utf-8") == "mine too"


def test_skips_when_workbuddy_not_installed(tmp_path):
    assert hub_agent.sync_workbuddy_skills(cfg("xhs-writing"), tmp_path / ".workbuddy" / "skills") is None
    assert not (tmp_path / ".workbuddy").exists()


def test_bridge_mode_keeps_stdout_clean(capsys):
    hub_agent.log_to_stderr()
    try:
        hub_agent.info("同步完成")
    finally:
        hub_agent.log_to_stderr(False)
    out = capsys.readouterr()
    assert out.out == "" and "同步完成" in out.err
