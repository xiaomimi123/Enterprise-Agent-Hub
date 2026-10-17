"""计费：岗位包选中枢模型 / 自带模型；中枢统一计量工具调用和 GPU 用量；GPU 额度在岗位包上。"""

import dataclasses
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import agent_api, db, generation, gpu, metering, policy
from app.main import app

client = TestClient(app)


def principal(**pack):
    return policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=policy.OFFICIAL,
                            pack={"name": "运营", "tools": ["image.generate"], **pack})


@pytest.fixture
def quiet(monkeypatch):
    audits, submitted = [], []
    monkeypatch.setattr(db, "add_audit", lambda **e: audits.append(e))
    monkeypatch.setattr(db, "pending_task_count", lambda org, user: 0)
    monkeypatch.setattr(gpu, "submit_task", lambda **t: submitted.append(t) or {**t, "id": "x", "ahead": 0})
    return audits, submitted


def test_gpu_quota_blocks_when_month_used_up(monkeypatch, quiet):
    audits, submitted = quiet
    monkeypatch.setattr(db, "gpu_seconds_this_month", lambda org, user: 10 * 60)
    with pytest.raises(generation.QuotaExceeded, match="10 分钟"):
        generation.submit_image(principal(gpu_quota_minutes=10), "tr", "猫")
    assert submitted == [] and audits[-1]["result"] == "拒绝" and "额度" in audits[-1]["detail"]


def test_gpu_quota_allows_under_limit_and_zero_means_unlimited(monkeypatch, quiet):
    _, submitted = quiet
    monkeypatch.setattr(db, "gpu_seconds_this_month", lambda org, user: 9 * 60 + 30)
    generation.submit_image(principal(gpu_quota_minutes=10), "tr", "猫")
    monkeypatch.setattr(db, "gpu_seconds_this_month", lambda org, user: 10 ** 7)
    generation.submit_image(principal(gpu_quota_minutes=0), "tr", "猫")
    assert len(submitted) == 2


def test_public_api_returns_403_on_quota(monkeypatch):
    from app import public_api
    monkeypatch.setattr(public_api, "_principal", lambda auth: principal())

    def over(*a, **k):
        raise generation.QuotaExceeded("本月 GPU 额度（10 分钟）已用完")
    monkeypatch.setattr(generation, "submit_image", over)
    r = client.post("/api/v1/images", json={"prompt": "猫"})
    assert r.status_code == 403 and "额度" in r.json()["detail"]


def test_enroll_skips_model_key_for_own_model_packs(monkeypatch):
    claims = {"owner": "o", "name": "u", "displayName": "U", "groups": ["o/video"]}
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda auth: claims)
    monkeypatch.setattr(agent_api.policy, "resolve_pack", lambda org, user, dept: {
        "name": "视频", "skills": [], "tools": [], "max_action_level": "需确认", "model_mode": "自带模型"})
    monkeypatch.setattr(agent_api.db, "add_audit", lambda **e: None)
    monkeypatch.setattr(agent_api, "settings", dataclasses.replace(agent_api.settings, default_model="deepseek-v4-flash"))

    class Boom:
        configured = True

        def ensure_token(self, name):
            raise AssertionError("自带模型的岗位包不应该创建模型 key")
    monkeypatch.setattr(agent_api, "NewApi", Boom)
    r = client.post("/api/agent/enroll", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["model"] is None and r.json()["model_mode"] == "自带模型"


def test_role_pack_accepts_new_fields_and_validates():
    r = client.patch("/api/role-packs/rp-video", json={"model_mode": "自带模型", "gpu_quota_minutes": 600})
    assert r.status_code == 200 and r.json()["model_mode"] == "自带模型" and r.json()["gpu_quota_minutes"] == 600
    assert client.patch("/api/role-packs/rp-video", json={"model_mode": "随便"}).status_code == 400
    assert client.patch("/api/role-packs/rp-video", json={"gpu_quota_minutes": -1}).status_code == 400


def test_hub_usage_aggregates_tools_and_gpu():
    now = datetime.now().astimezone()
    events = [
        {"user_name": "a", "kind": "检索", "tool": "kb.search", "result": "通过"},
        {"user_name": "a", "kind": "技能", "tool": "skill.read", "result": "通过"},
        {"user_name": "a", "kind": "拦截", "tool": "kb.search", "result": "拒绝"},     # 被拒的不算
        {"user_name": "a", "kind": "登录", "tool": "agent.enroll", "result": "通过"},  # 登录不算工具调用
        {"user_name": "b", "kind": "工具", "tool": "image.generate", "result": "通过"},
    ]
    tasks = [
        {"user_name": "b", "workflow": "image-gen", "status": "done", "images": ["1.png", "2.png"],
         "started_at": now - timedelta(seconds=90), "finished_at": now},
        {"user_name": "b", "workflow": "video-h3", "status": "done", "images": ["1.mp4"],
         "started_at": now - timedelta(seconds=30), "finished_at": now},
        {"user_name": "b", "workflow": "image-gen", "status": "failed", "images": [], "started_at": now, "finished_at": now},
    ]
    members = {"a": {"name": "甲", "dept_name": "运营部", "role_pack": "rp-1"}, "b": {"name": "乙", "dept_name": "设计部", "role_pack": "rp-2"}}
    packs = {"rp-1": {"name": "运营", "model_mode": "中枢模型", "gpu_quota_minutes": 0},
             "rp-2": {"name": "设计", "model_mode": "自带模型", "gpu_quota_minutes": 60}}
    out = metering.hub_usage(events, tasks, members, packs)
    assert out["totals"] == {"tool_calls": 3, "images": 2, "videos": 1, "gpu_minutes": 2.0}
    b = next(m for m in out["by_member"] if m["member_id"] == "b")
    assert b == {"member_id": "b", "member": "乙", "dept_name": "设计部", "role_pack": "设计", "model_mode": "自带模型",
                 "tool_calls": 1, "images": 2, "videos": 1, "gpu_minutes": 2.0, "gpu_quota_minutes": 60}
    assert [d["dept"] for d in out["by_dept"]] == ["设计部", "运营部"]  # 按 GPU 用量排序


def test_usage_endpoint_has_hub_section():
    hub = client.get("/api/usage?days=30").json()["hub"]
    assert set(hub["totals"]) == {"tool_calls", "images", "videos", "gpu_minutes"}
    assert hub["totals"]["tool_calls"] > 0 and hub["by_member"] and hub["by_dept"]
    assert {"model_mode", "gpu_quota_minutes", "gpu_minutes"} <= set(hub["by_member"][0])
