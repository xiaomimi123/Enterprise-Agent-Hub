import dataclasses
import json
import time

from app import comfyui, gpu


def test_parse_nodes():
    nodes = gpu.parse_nodes("gpu-01|GPU-01 设计部|http://10.0.0.2:8188|RTX 4090, bad-entry, gpu-02|GPU-02|http://x:8188")
    assert [n["id"] for n in nodes] == ["gpu-01", "gpu-02"]
    assert nodes[0]["gpu"] == "RTX 4090" and nodes[1]["gpu"] == ""


def test_workflow_placeholders_keep_types():
    wf, outputs = comfyui.load_workflow("xhs-cover", prompt="小红书封面，主文案「秋冬保湿」", seed=42, checkpoint="a.safetensors")
    assert outputs == ["9"]
    assert wf["3"]["inputs"]["seed"] == 42  # 整个值是占位符时保留整数类型
    assert wf["6"]["inputs"]["text"] == "小红书封面，主文案「秋冬保湿」"
    assert wf["4"]["inputs"]["ckpt_name"] == "a.safetensors"
    assert "_meta" not in wf


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


# ---- 视频工作流（MiniMax H3）----

def test_video_workflow_meta_and_placeholders():
    wf, outputs = comfyui.load_workflow("minimax-video", prompt="产品缓缓旋转，自然光",
                                        reference_image="ref.png", timeline_data='{"v":4}')
    assert outputs == ["7"]
    meta = comfyui.workflow_meta("minimax-video")
    assert meta["kind"] == "video" and meta["wait_seconds"] >= 600  # 视频是分钟级，不能按封面的 90 秒等
    assert wf["5"]["inputs"]["global_prompt"] == "产品缓缓旋转，自然光"
    assert wf["5"]["inputs"]["timeline_data"] == '{"v":4}'
    assert wf["5"]["inputs"]["total_frames"] == 107


def test_frame_grid_follows_17k_plus_5():
    # MiniMax H3 只接受 17k+5 的帧数，4 秒@24fps 应落到 107 帧
    assert comfyui.frames_for_seconds(4) == 107          # 96 帧向上取到 107
    assert comfyui.frames_for_seconds(3) == 73
    assert comfyui.frames_for_seconds(0.1) == 39         # 最短按 1 秒给（5/22 帧不足 1 秒，实际不可用）
    assert all((f - 5) % 17 == 0 for f in comfyui.FRAME_GRID)


def test_timeline_carries_reference_image_for_r2v():
    tl = json.loads(comfyui.build_timeline("镜头缓慢推近", "ref/up_1.png", frames=107, width=768, height=1344))
    assert tl["totalFrames"] == 107 and tl["width"] == 768 and tl["frameRate"] == 24.0
    # 图生视频必须带上参考图，否则会退化成文生视频
    assert tl["global"]["refs"] == [{"index": 0, "imageFile": "ref/up_1.png"}]
    assert tl["segments"][0]["refs"][0]["imageFile"] == "ref/up_1.png"
    assert tl["global"]["prompt"] == "镜头缓慢推近"


def test_result_collects_video_outputs(monkeypatch):
    """SaveVideo 节点把结果放在 outputs[].videos，取回时要和图片一样能拿到。"""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pid1": {"status": {"status_str": "success"}, "outputs": {
            "7": {"videos": [{"filename": "out.mp4", "subfolder": "video", "type": "output"}]}}}})

    c = comfyui.ComfyUI("http://node")
    c.http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://node")
    status, files = c.result("pid1", ["7"])
    assert status == "success" and files[0]["filename"] == "out.mp4"
    assert comfyui.is_video(files[0]["filename"]) and not comfyui.is_video("1.png")


def test_workflow_spec_from_registry_and_meta():
    """调度参数取自工作流注册表与模板 _meta：视频等 15 分钟、走 video.clip 权限。"""
    video = gpu.workflow_spec("minimax-video")
    assert video["kind"] == "video" and video["tool"] == "video.clip"
    assert video["wait_seconds"] == 900
    image = gpu.workflow_spec("xhs-cover")
    assert image["kind"] == "image" and image["tool"] == "image.cover" and image["wait_seconds"] == 90
    # 未注册的工作流按生图默认处理；模板不存在时也不该抛异常（只影响 agent 侧展示）
    assert gpu.workflow_spec("definitely-not-a-workflow")["tool"] == "image.cover"


def test_describe_separates_videos_from_images(monkeypatch):
    task = {"id": "gpu-1", "status": "done", "node_id": "gpu-01", "images": ["1.png", "out.mp4"],
            "started_at": None, "finished_at": None, "error": ""}
    monkeypatch.setattr(gpu.db, "queue_position", lambda _id: 0)
    out = gpu.describe(task)
    assert len(out["videos"]) == 1 and "/out.mp4?" in out["videos"][0]   # 链接带 ?exp=&sig= 后缀
    assert len(out["images"]) == 1 and "/1.png?" in out["images"][0]
