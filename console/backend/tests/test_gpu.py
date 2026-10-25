import dataclasses
import time

from app import comfyui, gpu


def test_parse_nodes():
    nodes = gpu.parse_nodes("gpu-01|GPU-01 设计部|http://10.0.0.2:8188|RTX 4090, bad-entry, gpu-02|GPU-02|http://x:8188")
    assert [n["id"] for n in nodes] == ["gpu-01", "gpu-02"]
    assert nodes[0]["gpu"] == "RTX 4090" and nodes[1]["gpu"] == ""


def test_workflow_placeholders_keep_types():
    wf, outputs = comfyui.load_workflow("image-gen", prompt="小红书封面，主文案「秋冬保湿」", seed=42, width=768, height=1024, count=3)
    assert outputs == ["9"]
    assert wf["8"]["inputs"]["seed"] == 42  # 整个值是占位符时保留整数类型
    assert wf["7"]["inputs"] == {"width": 768, "height": 1024, "batch_size": 3}
    assert wf["5"]["inputs"]["text"] == "小红书封面，主文案「秋冬保湿」"
    assert "_meta" not in wf


def test_video_workflow_and_frames():
    from app import generation
    wf, outputs = comfyui.load_workflow("video-h3", prompt="p", width=480, height=832, length=generation.video_frames(4))
    assert outputs == ["15"] and wf["9"]["inputs"]["length"] == 107 and wf["9"]["inputs"]["width"] == 480
    assert [generation.video_frames(s) for s in (2, 2.33, 5, 10)] == [56, 56, 124, 243]
    assert all(generation.video_frames(s) % 17 == 5 for s in (2, 3, 4.5, 7, 10))


def test_describe_splits_videos(monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(gpu, "file_url", lambda tid, n: f"u/{tid}/{n}")
    t = {"id": "t", "status": "done", "node_id": "n", "images": ["1.mp4"], "started_at": None, "finished_at": None, "error": ""}
    out = gpu.describe(t)
    assert out["videos"] == ["u/t/1.mp4"] and out["images"] == []
    assert "videos" not in gpu.describe({**t, "images": ["1.png"]})


def test_signed_links(monkeypatch, tmp_path):
    s = dataclasses.replace(gpu.settings, file_secret="secret", outputs_dir=str(tmp_path), public_url="http://hub")
    monkeypatch.setattr(gpu, "settings", s)
    (tmp_path / "t1").mkdir()
    (tmp_path / "t1" / "1.png").write_bytes(b"png")
    exp = int(time.time()) + 60
    assert gpu.verify_file("t1", "1.png", exp, gpu._sign("t1/1.png", exp)) is not None
    assert gpu.verify_file("t1", "1.png", exp, "bad") is None                         # 签名错误
    assert gpu.verify_file("t1", "1.png", 1, gpu._sign("t1/1.png", 1)) is None         # 已过期
    assert gpu.verify_file("t1", "../../x", exp, gpu._sign("t1/../../x", exp)) is None  # 跳出输出目录
    assert gpu.file_url("t1", "1.png").startswith("http://hub/api/files/t1/1.png?exp=")


def test_list_tasks_shapes_rows(monkeypatch):
    from datetime import datetime, timedelta

    from app import db
    now = datetime.now().astimezone()

    def row(i, status, workflow="image-gen", images=(), started=None, finished=None):
        return {"id": f"t{i}", "trace_id": "tr", "user_name": "u", "display_name": "U", "dept": "ops", "channel": "官方 agent",
                "workflow": workflow, "params": {"title": "标题", "prompt": "p", "width": 768, "height": 1024, "count": 2},
                "status": status, "node_id": "gpu-01" if started else None, "images": list(images), "error": "",
                "created_at": now - timedelta(minutes=10 - i), "started_at": started, "finished_at": finished}

    monkeypatch.setattr(db, "recent_gpu_tasks", lambda limit: [
        row(4, "queued"), row(3, "queued"), row(2, "running", started=now),
        row(1, "done", "video-h3", ["1.mp4"], now - timedelta(minutes=8), now - timedelta(minutes=7)),
    ])
    monkeypatch.setattr(gpu, "file_url", lambda tid, n: f"u/{tid}/{n}")
    out = gpu.list_tasks()
    by = {t["id"]: t for t in out["tasks"]}
    assert out["summary"] == {"queued": 2, "running": 1, "failed": 0, "done_today": 1}
    assert by["t3"]["ahead"] == 0 and by["t4"]["ahead"] == 1          # 先提交的排在前面
    assert by["t1"]["kind"] == "video" and by["t1"]["files"] == [{"type": "video", "url": "u/t1/1.mp4"}]
    assert by["t1"]["run_seconds"] == 60 and by["t1"]["wait_seconds"] == 60 and by["t4"]["size"] == "768×1024"


def test_public_api_maps_busy_to_429(monkeypatch):
    from fastapi.testclient import TestClient

    from app import generation, policy, public_api
    from app.main import app
    p = policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=policy.OFFICIAL, pack={})
    monkeypatch.setattr(public_api, "_principal", lambda auth: p)

    def busy(*a, **k):
        raise generation.Busy("你还有 3 个任务没完成")
    monkeypatch.setattr(generation, "submit_image", busy)
    r = TestClient(app).post("/api/v1/images", json={"prompt": "猫"})
    assert r.status_code == 429 and "没完成" in r.json()["detail"]


def test_public_api_cover_route(monkeypatch):
    from fastapi.testclient import TestClient

    from app import generation, policy, public_api
    from app.main import app
    p = policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=policy.OFFICIAL, pack={})
    monkeypatch.setattr(public_api, "_principal", lambda auth: p)
    got = {}

    def cover(principal, trace_id, title, description):
        got.update(title=title, description=description)
        return {"id": "c1", "ahead": 0, "trace_id": trace_id}
    monkeypatch.setattr(generation, "submit_cover", cover)
    client = TestClient(app)
    r = client.post("/api/v1/covers", json={"title": "秋天第一杯", "description": "暖色"})
    assert r.status_code == 202 and r.json()["task_id"] == "c1" and got == {"title": "秋天第一杯", "description": "暖色"}
    assert client.post("/api/v1/covers", json={"title": ""}).status_code == 422
    assert client.post("/api/v1/covers", json={"title": "长" * 41}).status_code == 422


def test_file_download_converts_to_png(monkeypatch, tmp_path):
    import io

    from fastapi.testclient import TestClient
    from PIL import Image

    from app.main import app
    s = dataclasses.replace(gpu.settings, file_secret="secret", outputs_dir=str(tmp_path), public_url="http://hub")
    monkeypatch.setattr(gpu, "settings", s)
    (tmp_path / "t1").mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), "red").save(buf, "WEBP")
    (tmp_path / "t1" / "1.webp").write_bytes(buf.getvalue())
    (tmp_path / "t1" / "2.webp").write_bytes(b"not an image")
    exp = int(time.time()) + 60
    client = TestClient(app)
    url = lambda n, fmt="": f"/api/files/t1/{n}?exp={exp}&sig={gpu._sign(f't1/{n}', exp)}" + (f"&fmt={fmt}" if fmt else "")
    assert client.get(url("1.webp")).content == buf.getvalue()                 # 不带 fmt 原样返回
    r = client.get(url("1.webp", "png"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (8, 6)
    assert client.get(url("2.webp", "png")).status_code == 415
    assert client.get(f"/api/files/t1/1.webp?exp={exp}&sig=bad&fmt=png").status_code == 404


def test_apimart_download_retries_network_errors_and_5xx_not_4xx():
    import httpx
    from app import imageapi
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if req.url.path == "/flaky" and calls["n"] < 3:
            raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
        if req.url.path == "/gone":
            return httpx.Response(404)
        if req.url.path == "/down":
            return httpx.Response(502)
        return httpx.Response(200, content=b"img")
    c = imageapi.ApimartClient("https://x", "k", "m", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.download("https://cdn/flaky", wait=0) == b"img" and calls["n"] == 3
    calls["n"] = 0
    try:
        c.download("https://cdn/gone", wait=0)
        raise AssertionError("4xx 应该直接失败")
    except imageapi.ImageApiError:
        assert calls["n"] == 1
    calls["n"] = 0
    try:
        c.download("https://cdn/down", wait=0)
        raise AssertionError("一直 5xx 应该失败")
    except imageapi.ImageApiError:
        assert calls["n"] == 3


def test_apimart_submit_sends_reference_images():
    import httpx
    import json as _json
    from app import imageapi
    seen = {}

    def handler(req):
        seen.update(_json.loads(req.content))
        return httpx.Response(200, json={"data": [{"task_id": "t1"}]})
    c = imageapi.ApimartClient("https://x", "k", "gpt-image-2", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.submit("猫", 1024, 1024, 1, image_urls=["data:image/png;base64,AA"]) == "t1"
    assert seen["image_urls"] == ["data:image/png;base64,AA"] and seen["size"] == "1:1"
    seen.clear()
    c.submit("猫", 1024, 1024, 1)
    assert "image_urls" not in seen


def test_public_api_with_references_and_capabilities(monkeypatch):
    from fastapi.testclient import TestClient

    from app import generation, policy, public_api
    from app.main import app
    p = policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=policy.OFFICIAL, pack={})
    monkeypatch.setattr(public_api, "_principal", lambda auth: p)
    got = {}

    def fake(principal, trace_id, prompt, aspect, count, references):
        got.update(prompt=prompt, aspect=aspect, count=count, refs=references)
        if len(references) > 1:
            raise generation.Denied("当前出图通道（本机 GPU）不支持参考图")
        return {"id": "r1", "ahead": 0, "trace_id": trace_id}
    monkeypatch.setattr(generation, "submit_image", fake)
    monkeypatch.setattr(generation, "capabilities", lambda: {"image_via": "第三方 API", "image_references": True})
    client = TestClient(app)
    r = client.post("/api/v1/images/with-references", data={"prompt": "换背景", "aspect": "3:4", "count": "2"},
                    files=[("images", ("a.png", b"A", "image/png"))])
    assert r.status_code == 202 and got == {"prompt": "换背景", "aspect": "3:4", "count": 2, "refs": [b"A"]}
    r = client.post("/api/v1/images/with-references", data={"prompt": "x"},
                    files=[("images", ("a.png", b"A", "image/png")), ("images", ("b.png", b"B", "image/png"))])
    assert r.status_code == 400 and "不支持参考图" in r.json()["detail"]
    assert client.get("/api/v1/capabilities").json()["image_via"] == "第三方 API"
