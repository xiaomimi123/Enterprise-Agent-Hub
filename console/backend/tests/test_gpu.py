import dataclasses
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
