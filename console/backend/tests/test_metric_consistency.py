"""指标口径：同一份数据在不同页面必须得到同一个结论（曾出现过成员页 / 应用健康 / 总览对不上）。"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import health, presence

NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
# 边界两侧都测：刚好 4 分 59 秒前、刚好 5 分钟前、3 分半前（原来健康页的窗口是 3 分钟）
AGES = {"fresh": 10, "three_half": 210, "just_inside": 299, "edge": 300, "old": 3600}


def _row(sec):
    return {"last_seen": NOW - timedelta(seconds=sec), "client": "CodeBuddy", "version": "0.5.11", "os": "Windows"}


def test_member_page_and_health_page_agree_for_every_age():
    rows = {u: _row(sec) for u, sec in AGES.items()}
    summary = health.merge_presence({"devices": [], "totals": {}}, rows, "0.5.11", now=NOW)
    health_online = {d["user_name"]: d["online"] for d in summary["devices"]}
    for user, row in rows.items():
        member_online = presence.member_agent(row, NOW)["agent_status"] == "在线"
        assert member_online == health_online[user] == presence.is_online(row["last_seen"], NOW), user
    # 总览的在线人数（成员状态计数）与应用健康顶部的在线人数一致
    assert summary["totals"]["online"] == sum(1 for r in rows.values() if presence.member_agent(r, NOW)["agent_status"] == "在线")
    assert summary["totals"]["online"] == 3   # fresh / three_half / just_inside；edge 和 old 是离线


def test_is_online_handles_missing_and_naive_times():
    assert presence.is_online(None, NOW) is False
    assert presence.is_online("", NOW) is False
    assert presence.is_online((NOW - timedelta(seconds=5)).replace(tzinfo=None), NOW) is True   # 无时区按 UTC
    assert presence.is_online((NOW - timedelta(seconds=5)).isoformat(), NOW) is True


def test_nobody_else_compares_against_the_online_window():
    """在线窗口只在 presence.py 里比较；别处再引用常量或写 `< 300` 之类的比较，就会又出现一个页面一个口径。"""
    root = Path(__file__).resolve().parent.parent / "app"
    bad = []
    for f in root.rglob("*.py"):
        if f.name == "presence.py":
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"ONLINE_(MINUTES|SECONDS)", line):
                bad.append(f"{f.relative_to(root)}:{n}: {line.strip()}")
    assert not bad, "在线窗口比较请调用 presence.is_online：\n" + "\n".join(bad)


def test_cost_is_only_read_from_raw_log_quota_in_the_repricing_code():
    """调用记录里的 quota 是当时按当时倍率记的，价格没设好会虚高（本月花费 ¥6802）。花费一律走 NewApi.repriced_quota；
    只有 newapi.py（重算本身 / 没配价格时的退路）和 db.attach_model_calls（调用方没传 quota_of 时的退路）可以直接读。"""
    root = Path(__file__).resolve().parent.parent / "app"
    users = sorted(f.name for f in root.rglob("*.py") if re.search(r'get\("quota"\)|\["quota"\]', f.read_text(encoding="utf-8")))
    assert users == ["db.py", "newapi.py"], users
