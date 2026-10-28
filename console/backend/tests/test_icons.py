"""应用快捷方式图标：/api/agent/icons/<应用 id>.ico 公开下载，只认 [a-z0-9._-]+.ico。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import agent_api


def client():
    app = FastAPI()
    app.include_router(agent_api.router)
    return TestClient(app)


def test_icon_is_served_as_a_real_ico_with_four_sizes():
    r = client().get("/api/agent/icons/xhs-workbench.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    b = r.content
    assert b[:4] == b"\x00\x00\x01\x00"                 # ICO 文件头
    assert int.from_bytes(b[4:6], "little") == 4        # 16 / 32 / 48 / 256
    assert b[22:30].startswith(b"\x89PNG") or b"\x89PNG" in b[:200]   # 每个尺寸是 PNG 压缩


def test_icon_rejects_bad_names_and_unknown_icons():
    c = client()
    for name in ("nope.ico", "xhs-workbench.png", "..%2F..%2Fetc%2Fpasswd", "XHS.ico", ".ico", "a%2Fb.ico", "xhs-workbench.ico.exe"):
        assert c.get(f"/api/agent/icons/{name}").status_code == 404, name
