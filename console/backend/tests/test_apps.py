"""应用注册表与签名下载：apps/<id>/app.json + <版本>.zip，下载只认注册表里的应用并校验签名。"""

import dataclasses
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import apps
from app.main import app

client = TestClient(app)


def make_app(root: Path, app_id="demo", version="1.0.0", **overrides):
    d = root / app_id
    d.mkdir(parents=True)
    meta = {"id": app_id, "name": "演示应用", "version": version, "description": "d", "entry": "run.mjs",
            "requires": {"node": ">=18"}, "start_args": ["start", "--open"], **overrides}
    (d / "app.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    with zipfile.ZipFile(d / f"{version}.zip", "w") as z:
        z.writestr("demo/run.mjs", "console.log('hi')")
    return d


@pytest.fixture
def root(tmp_path, monkeypatch):
    s = dataclasses.replace(apps.settings, apps_dir=str(tmp_path), file_secret="secret", public_url="http://hub:8088")
    monkeypatch.setattr(apps, "settings", s)
    return tmp_path


def test_lists_valid_app_with_all_fields(root):
    make_app(root)
    [a] = apps.list_apps()
    assert (a.id, a.name, a.version, a.entry) == ("demo", "演示应用", "1.0.0", "run.mjs")
    assert a.requires == {"node": ">=18"} and a.start_args == ["start", "--open"] and a.zip_path.name == "1.0.0.zip"


def test_broken_apps_are_skipped_not_fatal(root):
    make_app(root, "good")
    (root / "notjson").mkdir()
    (root / "notjson" / "app.json").write_text("{oops", encoding="utf-8")
    make_app(root, "noentry", entry="")                      # 缺 entry
    nozip = make_app(root, "nozip")
    (nozip / "1.0.0.zip").unlink()                           # 缺 zip
    assert [a.id for a in apps.list_apps()] == ["good"]


def test_directory_name_must_match_declared_id(root):
    d = make_app(root, "folder")
    meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
    meta["id"] = "other"
    (d / "app.json").write_text(json.dumps(meta), encoding="utf-8")
    assert apps.list_apps() == []                            # id 与目录名不一致：防止按声明的 id 去拼路径


@pytest.mark.parametrize("bad", ["", "../x", "..", "a/b", "A B", "demo/../demo"])
def test_get_app_never_builds_paths_from_input(root, bad):
    make_app(root)
    assert apps.get_app(bad) is None
    assert apps.get_app("demo").id == "demo"


def test_sha256_is_cached_by_mtime_and_size(root, monkeypatch):
    d = make_app(root)
    z = d / "1.0.0.zip"
    first = apps.sha256_of(z)
    reads = []
    real_open = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: reads.append(self) or real_open(self, *a, **k))
    assert apps.sha256_of(z) == first and reads == []        # 第二次不重读
    time.sleep(0.01)
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("demo/run.mjs", "console.log('changed')")
    assert apps.sha256_of(z) != first                        # 被替换后重算


def test_signed_url_roundtrip_and_tamper(root):
    make_app(root)
    a = apps.get_app("demo")
    url = apps.signed_zip_url(a)
    assert url.startswith("http://hub:8088/api/apps/demo/1.0.0.zip?exp=")
    q = dict(p.split("=") for p in url.split("?")[1].split("&"))
    exp, sig = int(q["exp"]), q["sig"]
    assert apps.verify_zip_request("demo", "1.0.0", exp, sig) == a.zip_path
    assert apps.verify_zip_request("demo", "1.0.0", exp, "0" * 32) is None            # 签名被改
    assert apps.verify_zip_request("demo", "9.9.9", exp, sig) is None                  # 版本不符
    assert apps.verify_zip_request("demo", "1.0.0", int(time.time()) - 5, apps._sign("demo", "1.0.0", int(time.time()) - 5)) is None  # 过期
    assert apps.verify_zip_request("../demo", "1.0.0", exp, sig) is None


def test_download_route(root):
    make_app(root)
    url = apps.signed_zip_url(apps.get_app("demo"))
    path = "/" + url.split("/", 3)[3]
    r = client.get(path)
    assert r.status_code == 200 and zipfile.ZipFile(__import__("io").BytesIO(r.content)).namelist() == ["demo/run.mjs"]
    assert client.get(path.replace("sig=", "sig=0")).status_code == 404
    assert client.get("/api/apps/demo/1.0.0.zip").status_code == 404                  # 没签名
