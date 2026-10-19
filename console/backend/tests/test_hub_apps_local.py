"""接入器在员工本机处理应用包：Node 检查、下载校验、安全解压。（启动与桥拦截见同文件后半部分）"""

import hashlib
import importlib.util
import io
import stat
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

_spec = importlib.util.spec_from_file_location("hub_agent", Path(__file__).resolve().parents[3] / "agent" / "hub_agent.py")
ha = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ha)


def make_zip(path: Path, entries: dict[str, str | bytes], symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
    return path


# ---------------- Node 检查 ----------------

def fake_run(stdout="", err=None, code=0):
    def run(cmd, **kw):
        if err:
            raise err
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")
    return run


@pytest.mark.parametrize("out,ok", [("v24.21.0\n", True), ("v18.0.0", True), ("18.20.1", True), ("v17.9.0", False), ("v18", True)])
def test_node_status_versions(out, ok):
    good, msg = ha.node_status({"node": ">=18"}, run=fake_run(out))
    assert good is ok
    if ok:
        assert msg.lstrip("v").split(".")[0] == out.strip().lstrip("v").split(".")[0]


def test_node_missing_or_garbage_gives_install_guidance(monkeypatch):
    for run in (fake_run(err=FileNotFoundError()), fake_run("command not found"), fake_run("", code=1)):
        good, msg = ha.node_status({"node": ">=18"}, run=run)
        assert good is False and "Node.js" in msg and "18" in msg
    monkeypatch.setattr(ha.sys, "platform", "darwin")
    assert "brew install node" in ha.node_status({"node": ">=18"}, run=fake_run(err=FileNotFoundError()))[1]
    monkeypatch.setattr(ha.sys, "platform", "win32")
    assert "winget" in ha.node_status({"node": ">=18"}, run=fake_run(err=FileNotFoundError()))[1]


def test_node_requirement_absent_means_no_check():
    assert ha.node_status({}, run=fake_run(err=FileNotFoundError())) == (True, "")


# ---------------- 安全解压 ----------------

def test_extracts_normal_zip(tmp_path):
    z = make_zip(tmp_path / "a.zip", {"app/run.mjs": "x", "app/sub/b.txt": "y"})
    ha.safe_extract(z, tmp_path / "out")
    assert (tmp_path / "out" / "app" / "sub" / "b.txt").read_text() == "y"
    assert not (tmp_path / "out.partial").exists()


@pytest.mark.parametrize("evil", ["../escape.txt", "app/../../escape.txt", "/abs/escape.txt", "C:/escape.txt", "..\\escape.txt"])
def test_rejects_path_escape(tmp_path, evil):
    z = make_zip(tmp_path / "e.zip", {"ok.txt": "1", evil: "x"})
    with pytest.raises(ValueError, match="路径"):
        ha.safe_extract(z, tmp_path / "out")
    assert not (tmp_path / "out").exists() and not (tmp_path / "out.partial").exists()   # 不留下半成品
    assert not (tmp_path.parent / "escape.txt").exists()


def test_rejects_symlink_entries(tmp_path):
    z = make_zip(tmp_path / "s.zip", {"ok.txt": "1"}, symlink="link")
    with pytest.raises(ValueError, match="符号链接"):
        ha.safe_extract(z, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_rejects_zip_bombs(tmp_path):
    big = make_zip(tmp_path / "big.zip", {"a.bin": b"0" * 4096})
    with pytest.raises(ValueError, match="大小"):
        ha.safe_extract(big, tmp_path / "o1", max_bytes=1000)
    many = make_zip(tmp_path / "many.zip", {f"f{i}.txt": "x" for i in range(20)})
    with pytest.raises(ValueError, match="文件数"):
        ha.safe_extract(many, tmp_path / "o2", max_files=10)
    assert not (tmp_path / "o1").exists() and not (tmp_path / "o2").exists()


def test_lying_headers_are_caught_while_writing(tmp_path, monkeypatch):
    """zip 头里声明的大小可以造假：预检看到的是假的小值，按实际写出的字节数再限一次。"""
    z = make_zip(tmp_path / "lie.zip", {"a.bin": b"0" * 4096})
    real_infolist = zipfile.ZipFile.infolist

    class Liar:  # 预检读到的 file_size 是假的，其余属性照旧
        def __init__(self, info):
            self._i = info

        def __getattr__(self, k):
            return 1 if k == "file_size" else getattr(self._i, k)
    monkeypatch.setattr(zipfile.ZipFile, "infolist", lambda self: [Liar(i) for i in real_infolist(self)])
    real_open = zipfile.ZipFile.open
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda self, i, *a, **k: real_open(self, getattr(i, "_i", i), *a, **k))
    with pytest.raises(ValueError, match="大小"):
        ha.safe_extract(z, tmp_path / "out", max_bytes=1000)
    assert not (tmp_path / "out").exists() and not (tmp_path / "out.partial").exists()


# ---------------- 下载与校验 ----------------

def client_for(content: bytes, status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, content=content)))


def test_fetch_verified_ok_and_mismatch(tmp_path):
    data = b"zip-bytes"
    good = hashlib.sha256(data).hexdigest()
    p = ha.fetch_verified("http://hub/x.zip", good, tmp_path / "x.zip", client_for(data))
    assert p.read_bytes() == data
    with pytest.raises(ValueError, match="校验失败"):
        ha.fetch_verified("http://hub/x.zip", "0" * 64, tmp_path / "y.zip", client_for(data))
    assert not (tmp_path / "y.zip").exists() and not list(tmp_path.glob("*.part"))       # 不一致的文件被删除
    with pytest.raises(ValueError, match="下载失败"):
        ha.fetch_verified("http://hub/x.zip", good, tmp_path / "z.zip", client_for(b"", status=404))


# ---------------- 目录与版本清理 ----------------

def test_app_dir_rejects_bad_ids_and_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "HOME", tmp_path)
    assert ha.app_dir("xhs-workbench", "0.6.1") == tmp_path / "apps" / "xhs-workbench" / "0.6.1"
    for bad in ("../x", "a/b", "", "A B"):
        with pytest.raises(ValueError):
            ha.app_dir(bad, "1")
    with pytest.raises(ValueError):
        ha.app_dir("ok", "../1")


def test_prune_keeps_newest_two_versions(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(ha, "HOME", tmp_path)
    for i, v in enumerate(["0.5.0", "0.6.0", "0.6.1"]):
        d = ha.app_dir("xhs", v)
        d.mkdir(parents=True)
        os.utime(d, (1000 + i, 1000 + i))
    ha.prune_versions("xhs", keep=2)
    assert sorted(p.name for p in (tmp_path / "apps" / "xhs").iterdir()) == ["0.6.0", "0.6.1"]
