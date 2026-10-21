from datetime import datetime, timedelta, timezone

import pytest

from app import auth, kbmeta

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone(timedelta(hours=8)))


def kb(days=90, last_days_ago=10):
    return {"review_every_days": days, "last_reviewed_at": (NOW - timedelta(days=last_days_ago)).isoformat() if last_days_ago is not None else None}


def test_overdue_and_due_in_days():
    assert not kbmeta.is_overdue(kb(90, 10), NOW) and kbmeta.due_in_days(kb(90, 10), NOW) == 80
    assert kbmeta.is_overdue(kb(90, 100), NOW) and kbmeta.due_in_days(kb(90, 100), NOW) == -10
    assert not kbmeta.is_overdue(kb(0, 999), NOW) and kbmeta.due_in_days(kb(0, 999), NOW) is None   # 0 = 不需要复核
    assert kbmeta.is_overdue(kb(90, None), NOW) and kbmeta.due_in_days(kb(90, None), NOW) == -1     # 从没复核过


def test_clean_validates_every_field():
    ok = kbmeta._clean({"name": "新库", "dept": "ops", "classification": "内部", "category": "话术", "owner": " zhou ", "review_every_days": "30",
                        "external_access": 1, "description": "x" * 500}, {"ops"})
    assert ok["dept_id"] == "ops" and ok["owner"] == "zhou" and ok["review_every_days"] == 30 and ok["external_access"] is True and len(ok["description"]) == 200
    for bad in [{"name": ""}, {"name": "x" * 31}, {"name": "品牌调性与人设"}, {"dept": "nope"}, {"classification": "绝密"}, {"category": "乱写"},
                {"review_every_days": "abc"}, {"review_every_days": -1}, {"review_every_days": 99999}]:
        with pytest.raises(kbmeta.KbMetaError):
            kbmeta._clean(bad, {"ops"})
    assert kbmeta._clean({"dept": "all"}, {"ops"})["dept_id"] == "all"
    assert kbmeta._clean({"name": "品牌调性与人设", "_id": "kb-brand"}, None)["name"] == "品牌调性与人设"   # 改自己的属性不算重名


def test_confidential_cannot_be_external(monkeypatch):
    with pytest.raises(kbmeta.KbMetaError):
        kbmeta.create({"name": "新的机密库", "dept": "all", "classification": "机密", "external_access": True}, None)
    with pytest.raises(kbmeta.KbMetaError):
        kbmeta.update("kb-brand", {"classification": "机密", "external_access": True}, None)
    with pytest.raises(kbmeta.KbMetaError):
        kbmeta.create({"name": "缺字段"}, None)


def test_refresh_without_database_keeps_the_builtin_registry():
    from app.content import KB_REGISTRY
    before = dict(KB_REGISTRY)
    kbmeta.refresh(force=True)
    assert dict(KB_REGISTRY) == before and "kb-brand" in KB_REGISTRY


def test_seed_registry_has_the_new_fields_after_a_real_refresh_shape():
    row = {"id": "kb-x", "name": "x", "dept_id": "ops", "classification": "内部", "source": "控制台", "external_access": False, "category": "话术",
           "owner": "zhou", "review_every_days": 90, "description": "", "last_reviewed_at": NOW}
    e = kbmeta._entry(row)
    assert e["dept"] == "ops" and e["category"] == "话术" and e["last_reviewed_at"].startswith("2026-10-21")


def allowed(role, method, path):
    return any(method == m and rx.match(path) for m, rx in auth.ROLE_ALLOWED[role])


def test_kb_settings_routes_are_allowlisted_for_boss_and_manager_but_handlers_decide():
    for role in ("manager", "boss"):
        assert allowed(role, "PATCH", "/api/knowledge-bases/kb-brand") and allowed(role, "POST", "/api/knowledge-bases/kb-brand/reviewed")
        assert allowed(role, "POST", "/api/knowledge-bases")  # 路径放行，新建只有管理员 / 老板由 kb_api 判断
    assert not allowed("manager", "DELETE", "/api/knowledge-bases/kb-brand")


def test_kb_api_field_rules():
    from app import kb_api
    assert {"classification", "external_access", "dept", "name"} <= kb_api.ADMIN_ONLY_FIELDS
    assert {"owner", "category", "review_every_days"} <= kb_api.MANAGER_FIELDS and not (kb_api.MANAGER_FIELDS & kb_api.ADMIN_ONLY_FIELDS)
