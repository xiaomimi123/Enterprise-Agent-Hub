"""应用健康：去隐私、清洗、限流、汇总（health.py）。"""

from datetime import datetime, timedelta, timezone

from app import health

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)


def test_redact_removes_private_bits():
    raw = ("C:\\Users\\张三\\HubApps\\apps\\x.mjs failed; /Users/lisi/HubApps; token=abc123 Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig "
           "sk-abcdefghijkl mail a.b@corp.com phone 13812345678 url http://192.168.0.41:8088/callback?code=xyz&state=1")
    out = health.redact(raw)
    for leaked in ("张三", "lisi", "abc123", "eyJhbGci", "sk-abcdefghijkl", "a.b@corp.com", "13812345678", "code=xyz"):
        assert leaked not in out, leaked
    assert "~\\HubApps" in out and "~/HubApps" in out
    assert "http://192.168.0.41:8088/callback" in out
    assert len(health.redact("x" * 1000)) == health.MAX_MESSAGE


def test_clean_whitelists_and_normalises():
    ev = health.clean({"stage": "launch", "ok": False, "code": "port_in_use", "message": "C:\\Users\\王五\\a", "os": "Windows 10",
                       "at": (NOW - timedelta(hours=1)).isoformat(), "prompt": "不该上传", "app_id": "xhs-workbench"}, NOW)
    assert ev["code"] == "PORT_IN_USE" and ev["message"] == "~\\a" and "prompt" not in ev
    assert ev["at"] == NOW - timedelta(hours=1)
    # 成功：错误码一律 OK、不带原文
    ok = health.clean({"stage": "install", "ok": True, "code": "NODE_MISSING", "message": "x", "at": NOW.isoformat()}, NOW)
    assert ok["code"] == "OK" and ok["message"] == ""
    # 不认识的码归为未分类；阶段不对、超过保留期的丢弃；未来时间被截住
    assert health.clean({"stage": "install", "ok": False, "code": "WHATEVER"}, NOW)["code"] == "UNKNOWN"
    assert health.clean({"stage": "hack", "ok": False}, NOW) is None
    assert health.clean({"stage": "install", "ok": False, "at": (NOW - timedelta(days=8)).isoformat()}, NOW) is None
    assert health.clean({"stage": "install", "ok": True, "at": (NOW + timedelta(days=2)).isoformat()}, NOW)["at"] == NOW + timedelta(minutes=5)
    assert health.clean("not a dict", NOW) is None


def test_rate_limit_per_person():
    health._rate.clear()
    assert health.allow("org", "a", health.RATE_LIMIT, now=1000.0)
    assert not health.allow("org", "a", 1, now=1001.0)
    assert health.allow("org", "b", 1, now=1001.0)  # 别人不受影响
    assert health.allow("org", "a", 1, now=1000.0 + 3601)  # 一小时后恢复


def _row(user, device, stage, ok, code="OK", minutes=0, **kw):
    return {"user_name": user, "display_name": "", "device_id": device, "stage": stage, "ok": ok, "code": code,
            "message": kw.get("message", ""), "os": kw.get("os", "Windows 10"), "os_version": "", "arch": "x64",
            "agent": kw.get("agent", "WorkBuddy"), "agent_version": "", "connector_version": "0.5.0",
            "app_id": kw.get("app_id", ""), "app_version": kw.get("app_version", ""), "at": NOW - timedelta(minutes=minutes)}


def test_summarize_rates_codes_and_devices():
    rows = [  # 倒序
        _row("a", "d1", "launch", True, minutes=1, app_id="xhs-workbench", app_version="0.7.9"),
        _row("b", "d2", "install", False, "NET_UNREACHABLE", minutes=2, message="连不上 192.168.0.41"),
        _row("a", "d1", "launch", False, "PORT_IN_USE", minutes=3, app_id="xhs-workbench", app_version="0.7.9"),
        _row("c", "d3", "install", False, "NET_UNREACHABLE", minutes=4, os="macOS"),
        _row("a", "d1", "install", True, minutes=5),
    ]
    s = health.summarize(rows, {"a": "张三"})
    t = s["totals"]
    assert (t["events"], t["fails"], t["people"], t["devices"], t["fail_people"]) == (5, 3, 3, 3, 3)
    assert t["install"] == {"total": 3, "ok": 1, "rate": 0.333} and t["launch"]["rate"] == 0.5 and t["login"]["rate"] is None
    top = s["codes"][0]
    assert top["code"] == "NET_UNREACHABLE" and top["count"] == 2 and top["people"] == 2
    assert top["os"] == {"Windows 10": 1, "macOS": 1} and top["sample"] == "连不上 192.168.0.41" and top["fix"]
    devs = {d["user_name"]: d for d in s["devices"]}
    assert devs["a"]["display_name"] == "张三" and devs["a"]["failing"] is False  # 失败之后又成功了
    assert devs["a"]["app_version"] == "xhs-workbench 0.7.9" and devs["a"]["fails"] == 1
    assert devs["b"]["failing"] and devs["b"]["last_code"] == "NET_UNREACHABLE"
    blank = health.summarize([{**_row("x", "d9", "task", False, "ACCESS_LOCKED"), "os": "", "agent": "", "connector_version": ""},
                              _row("x", "d9", "launch", True, minutes=5)])["devices"][0]
    assert (blank["os"], blank["agent"], blank["connector_version"]) == ("Windows 10", "WorkBuddy", "0.5.0")  # 最新一条没带的用较早的补
    assert [d["user_name"] for d in s["devices"]][-1] == "a"  # 还在失败的排前面
    assert "NET_UNREACHABLE" in s["catalog"] and s["catalog"]["UNKNOWN"]["label"] == "未分类"


def test_demo_data_and_api_in_demo_mode():
    from fastapi.testclient import TestClient
    from app import main
    c = TestClient(main.app)
    s = c.get("/api/health/summary?days=7").json()
    assert s["totals"]["events"] == len(health.demo_rows()) and s["codes"][0]["code"] == "NET_UNREACHABLE"
    d = s["devices"][0]
    tl = c.get(f"/api/health/device?user_name={d['user_name']}&device_id={d['device_id']}").json()["events"]
    assert tl and all(e["label"] for e in tl)
    assert c.get("/api/health/summary?days=8").status_code == 422  # 只保留 7 天


def test_summarize_empty():
    s = health.summarize([])
    assert s["totals"]["events"] == 0 and s["codes"] == [] and s["devices"] == []
