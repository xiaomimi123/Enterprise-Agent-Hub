from datetime import datetime, timedelta, timezone

import pytest

from app import work

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone(timedelta(hours=8)))
PACKS = {"rp-xhs-ops": {"name": "小红书运营"}, "rp-designer": {"name": "设计师"}, "rp-general": {"name": "通用"}}


def ev(user, tool="kb.search", result="通过", hours_ago=1, dept="ops"):
    return {"user_name": user, "display_name": user.upper(), "dept": dept, "tool": tool, "result": result, "ts": NOW - timedelta(hours=hours_ago)}


def item(user, title, status="已完成", kind="笔记", hours_ago=1, dept="ops"):
    return {"id": 1, "user_name": user, "display_name": user.upper(), "dept": dept, "kind": kind, "title": title, "status": status,
            "progress": 100, "link": "", "note": "卡在审核" if status == "受阻" else "", "source": "agent", "updated_at": NOW - timedelta(hours=hours_ago)}


def build(**kw):
    base = dict(days=1, events=[], items=[], tasks=[], assignments={}, packs=PACKS, now=NOW)
    return work.build_report(**{**base, **kw})


def test_items_and_activity_are_grouped_by_role_and_person():
    r = build(events=[ev("a"), ev("a", result="拒绝"), ev("b", dept="design")],
              items=[item("a", "笔记1"), item("a", "笔记2", "待审核"), item("b", "封面", kind="封面", dept="design")],
              tasks=[{"user_name": "a", "workflow": "image-gen", "status": "done", "images": ["x", "y"], "created_at": NOW - timedelta(hours=2), "finished_at": NOW},
                     {"user_name": "a", "workflow": "h3-video", "status": "done", "images": [], "created_at": NOW, "finished_at": NOW},
                     {"user_name": "a", "workflow": "image-gen", "status": "failed", "images": [], "created_at": NOW}])
    a = next(p for p in r["people"] if p["user_name"] == "a")
    assert a["role"] == "小红书运营" and a["items"]["已完成"] == 1 and a["items"]["待审核"] == 1
    assert (a["calls"], a["denied"], a["images"], a["videos"]) == (2, 1, 2, 1)
    roles = {x["role"]: x for x in r["roles"]}
    assert roles["小红书运营"]["items"]["total"] == 2 and roles["设计师"]["items"]["已完成"] == 1
    assert r["totals"]["items"]["total"] == 3 and r["totals"]["people"] == 2


def test_period_is_calendar_days_and_old_data_is_ignored():
    r = build(events=[ev("a", hours_ago=30)], items=[item("a", "昨天的", hours_ago=30)])
    assert r["totals"]["items"]["total"] == 0 and r["totals"]["calls"] == 0
    assert build(days=2, items=[item("a", "昨天的", hours_ago=30)])["totals"]["items"]["total"] == 1


def test_inactive_members_and_blocked_items_are_called_out():
    r = build(members=[{"user_name": "a", "name": "A", "dept": "ops"}, {"user_name": "z", "name": "小周", "dept": "ops"}],
              events=[ev("a")], items=[item("a", "对标报告", "受阻", "对标报告")])
    assert r["inactive"] == ["小周"] and [i["title"] for i in r["blocked"]] == ["对标报告"]
    assert "受阻" in r["digest"] and "小周" in r["digest"]


def test_digest_says_when_nobody_reported_outcomes():
    assert "report_work" in build(events=[ev("a")])["digest"]


def test_work_report_events_are_not_counted_as_activity_and_person_filter_works():
    r = build(events=[ev("a", tool="work.report"), ev("b")], person="B")
    assert [p["user_name"] for p in r["people"]] == ["b"]


@pytest.mark.parametrize("bad", [{"title": ""}, {"title": "x", "status": "完成了"}, {"title": "x", "progress": "abc"},
                                 {"title": "x", "link": r"C:\secret\a.txt"}])
def test_bad_reports_are_rejected(bad):
    with pytest.raises(work.BadReport):
        work._clean(bad)


def test_clean_defaults_and_limits():
    c = work._clean({"title": "t" * 500, "kind": "", "progress": 150, "status": "进行中", "note": "n" * 999})
    assert len(c["title"]) == work.MAX_TITLE and c["kind"] == "其他" and c["progress"] == 100 and len(c["note"]) == work.MAX_NOTE
    assert work._clean({"title": "x"})["progress"] == 100 and work._clean({"title": "x", "status": "待审核"})["progress"] == 0
    assert work._clean({"title": "x", "status": "已完成", "progress": 30})["progress"] == 100


def test_demo_mode_report_endpoint_is_empty_not_an_error():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get("/api/work/report?days=7")
    assert r.status_code == 200 and r.json()["totals"]["items"]["total"] == 0
