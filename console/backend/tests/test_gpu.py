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
