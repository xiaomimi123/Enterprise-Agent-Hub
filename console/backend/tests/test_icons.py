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


def test_bundle_info_summarizes_manifest_without_leaking_file_names(tmp_path, monkeypatch):
    """控制台「接入方式」页的底座包状态：只含版本、时间、各组件版本 / 大小；没构建过是 None。"""
    import json
    from app.config import settings

    object.__setattr__(settings, "bundle_dir", str(tmp_path))
    assert agent_api.bundle_info() is None                       # 没有 manifest
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
    assert agent_api.bundle_info() is None                       # 坏文件不报错
    (tmp_path / "manifest.json").write_text(json.dumps({"base": "1.0.1", "built_at": "2026-10-28T03:00:00Z", "components": {
        "node": {"version": "22.23.4", "size": 35604229, "file": "node-v22.23.4-win-x64.zip", "sha256": "ab" * 32},
        "wheels": {"version": "8 wheels", "size": 703586, "file": "wheels-x.zip", "sha256": "cd" * 32}}}), encoding="utf-8")
    info = agent_api.bundle_info()
    assert info["base"] == "1.0.1" and info["built_at"].startswith("2026-10-28")
    assert [(c["name"], c["version"], c["size"]) for c in info["components"]] == [("node", "22.23.4", 35604229), ("wheels", "8 wheels", 703586)]
    assert "sha256" not in json.dumps(info) and "file" not in json.dumps(info)
