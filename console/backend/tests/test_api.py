from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_all_read_endpoints():
    for path in ["/api/health", "/api/overview", "/api/departments", "/api/members", "/api/role-packs",
                 "/api/role-packs/rp-xhs-ops", "/api/catalog", "/api/skills", "/api/skills/xhs-cover",
                 "/api/knowledge-bases", "/api/knowledge-bases/kb-brand/documents", "/api/audit/traces",
                 "/api/audit/traces/tr-0001", "/api/usage?days=7"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)


def test_demo_data_shape():
    assert len(client.get("/api/members").json()) == 50
    ov = client.get("/api/overview").json()
    assert ov["stats"]["denied_today"] >= 2
    assert ov["stats"]["pending_approvals"] >= 1


def test_assign_and_update_role_pack():
    m = client.get("/api/members", params={"dept": "tech"}).json()[0]
    r = client.put(f"/api/members/{m['id']}/role-pack", json={"role_pack_id": "rp-designer"})
    assert r.json()["role_pack"] == "rp-designer"
    r = client.patch("/api/role-packs/rp-cs", json={"monthly_quota": 450, "external_access": "关闭"})
    assert r.json()["monthly_quota"] == 450 and r.json()["external_access"] == "关闭"


def test_not_found():
    assert client.get("/api/skills/nope").status_code == 404
    assert client.patch("/api/role-packs/rp-cs", json={"monthly_quota": -1}).status_code == 400
