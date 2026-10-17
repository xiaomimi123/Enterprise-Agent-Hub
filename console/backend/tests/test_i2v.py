"""图生视频：参考图校验、只接受中枢签名链接（防 SSRF）、调度时上传到 ComfyUI、HTTP 上传接口。"""

import dataclasses
import io
import time

import pytest
from PIL import Image

from app import db, generation, gpu, policy


def png(w=64, h=80) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 80)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def env(monkeypatch, tmp_path):
    s = dataclasses.replace(gpu.settings, outputs_dir=str(tmp_path), file_secret="sec", public_url="http://hub:8088",
                            gpu_max_pending_per_user=0)
    for m in (gpu, generation):
        monkeypatch.setattr(m, "settings", s)
    audits, submitted = [], []
    monkeypatch.setattr(db, "add_audit", lambda **e: audits.append(e))
    monkeypatch.setattr(gpu, "submit_task", lambda **t: submitted.append(t) or {**t, "id": "gpu-1", "ahead": 0})
    p = policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=policy.OFFICIAL,
                         pack={"name": "运营", "tools": ["video.generate"]})
    return p, tmp_path, submitted, audits


def test_image_is_stored_and_passed_to_worker(env):
    p, tmp, submitted, _ = env
    generation.submit_video_from_image(p, "tr", png(), "让画面动起来", seconds=4)
    t = submitted[0]
    assert t["workflow"] == "video-h3-i2v" and t["params"]["length"] == 107 and t["params"]["tool"] == "video.generate"
    saved = tmp / t["params"]["_input"]
    assert saved.is_file() and saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_rejects_non_images_and_oversized(env):
    p, *_ = env
    with pytest.raises(generation.Denied, match="图片"):
        generation.submit_video_from_image(p, "tr", b"not an image", "x")
    with pytest.raises(generation.Denied, match="MB"):
        generation.submit_video_from_image(p, "tr", b"\x89PNG" + b"0" * (generation.MAX_IMAGE_BYTES + 1), "x")


def test_requires_video_permission(env):
    p, *_ = env
    p.pack["tools"] = []
    with pytest.raises(generation.Denied, match="无权"):
        generation.submit_video_from_image(p, "tr", png(), "x")


def test_image_url_must_be_a_signed_hub_link(env):
    p, tmp, *_ = env
    (tmp / "gpu-src").mkdir()
    (tmp / "gpu-src" / "1.png").write_bytes(png())
    good = gpu.file_url("gpu-src", "1.png")
    assert generation.image_from_hub_url(good) == (tmp / "gpu-src" / "1.png").read_bytes()
    for bad in ("http://evil.example.com/a.png", "http://169.254.169.254/latest/meta-data",
                good.replace("sig=", "sig=0"), "http://hub:8088/api/files/gpu-src/1.png", "file:///etc/passwd"):
        with pytest.raises(generation.Denied):
            generation.image_from_hub_url(bad)


def test_worker_uploads_input_before_submitting(env, monkeypatch):
    _, tmp, *_ = env
    (tmp / "_inputs").mkdir()
    (tmp / "_inputs" / "abc.png").write_bytes(png())
    calls = []

    class FakeComfy:
        def __init__(self, url):
            pass

        def upload_image(self, name, data):
            calls.append(("upload", name, len(data)))
            return f"uploaded-{name}"

        def submit(self, wf):
            calls.append(("submit", wf["16"]["inputs"]["image"]))
            return "pid"

    task = {"id": "gpu-9", "workflow": "video-h3-i2v", "trace_id": "t", "org": "o", "user_name": "u",
            "display_name": "U", "dept": "d", "channel": "c",
            "params": {"prompt": "p", "length": 107, "_input": "_inputs/abc.png", "tool": "video.generate"}}
    monkeypatch.setattr(gpu, "ComfyUI", FakeComfy)
    monkeypatch.setattr(db, "claim_task_for", lambda node_id: task)
    updates = {}
    monkeypatch.setattr(db, "update_gpu_task", lambda tid, **f: updates.update(f))
    gpu._dispatch([{"id": "n", "name": "N", "url": "http://c"}], {"n"})
    assert calls[0][0] == "upload" and calls[0][1] == "hub-gpu-9.png"
    assert calls[1] == ("submit", "uploaded-hub-gpu-9.png") and updates["prompt_id"] == "pid"


def test_public_api_accepts_upload(monkeypatch):
    from fastapi.testclient import TestClient

    from app import public_api
    from app.main import app
    p = policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=policy.OFFICIAL, pack={})
    monkeypatch.setattr(public_api, "_principal", lambda auth: p)
    got = {}

    def fake(principal, trace_id, image, prompt, seconds=4):
        got.update(image=image, prompt=prompt, seconds=seconds)
        return {"id": "gpu-2", "ahead": 1, "trace_id": trace_id}
    monkeypatch.setattr(generation, "submit_video_from_image", fake)
    r = TestClient(app).post("/api/v1/videos/from-image", data={"prompt": "动起来", "seconds": "5"},
                             files={"image": ("a.png", png(), "image/png")})
    assert r.status_code == 202 and r.json()["task_id"] == "gpu-2"
    assert got["prompt"] == "动起来" and got["seconds"] == 5 and got["image"][:4] == b"\x89PNG"
