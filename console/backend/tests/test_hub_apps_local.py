"""接入器在员工本机处理应用包：Node 检查、下载校验、安全解压。（启动与桥拦截见同文件后半部分）"""

import hashlib
import importlib.util
import io
import json
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
    monkeypatch.setattr(ha, "HUB_APPS", tmp_path)  # 新装的应用放应用根目录：测试里让它和 HOME 是同一个临时目录
    assert ha.app_dir("xhs-workbench", "0.6.1") == tmp_path / "apps" / "xhs-workbench" / "0.6.1"
    for bad in ("../x", "a/b", "", "A B"):
        with pytest.raises(ValueError):
            ha.app_dir(bad, "1")
    with pytest.raises(ValueError):
        ha.app_dir("ok", "../1")


def test_prune_keeps_newest_two_versions(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(ha, "HOME", tmp_path)
    monkeypatch.setattr(ha, "HUB_APPS", tmp_path)  # 新装的应用放应用根目录：测试里让它和 HOME 是同一个临时目录
    for i, v in enumerate(["0.5.0", "0.6.0", "0.6.1"]):
        d = ha.app_dir("xhs", v)
        d.mkdir(parents=True)
        os.utime(d, (1000 + i, 1000 + i))
    ha.prune_versions("xhs", keep=2)
    assert sorted(p.name for p in (tmp_path / "apps" / "xhs").iterdir()) == ["0.6.0", "0.6.1"]


# ================= 本机启动 =================

import json  # noqa: E402
import threading  # noqa: E402

ENTRY = "xhs-workbench/scripts/workbench.mjs"


def build_ticket(tmp_path, version="0.6.1", payload="x", **extra):
    z = make_zip(tmp_path / f"srv-{version}.zip", {ENTRY: payload, "xhs-workbench/SKILL.md": "# skill"})
    data = z.read_bytes()
    return {"app_id": "xhs-workbench", "name": "小红书运营工作台", "version": version, "sha256": hashlib.sha256(data).hexdigest(),
            "download_url": "http://hub/dl.zip", "entry": ENTRY, "requires": {"node": ">=18"},
            "setup_args": ["setup"], "start_args": ["start", "--open"], **extra}, data


class Recorder:
    """假的 subprocess.run：记录每次调用，按子命令返回预设输出。"""

    def __init__(self, start_out="工作台已启动。\nURL: http://127.0.0.1:17890/?t=abc\n", node="v24.21.0", hang=False, setup_out="初始化完成"):
        self.calls, self.start_out, self.node, self.hang, self.setup_out = [], start_out, node, hang, setup_out

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[:2] == ["node", "-v"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.node, stderr="")
        if self.hang and "start" in cmd:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))
        return subprocess.CompletedProcess(cmd, 0, stdout=self.start_out if "start" in cmd else self.setup_out, stderr="")

    def started(self):
        return [c for c, _ in self.calls if "start" in c]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setattr(ha, "HOME", h)
    monkeypatch.setattr(ha, "HUB_APPS", h)
    monkeypatch.setattr(ha, "find_uv", lambda: "/usr/bin/uv")
    return h


def launch(ticket, data, run):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data)))
    return ha.launch_app(ticket, "http://hub", {"access_token": "t"}, run=run, client=client)


def test_parse_url():
    assert ha.parse_url("工作台已启动。\nURL: http://127.0.0.1:17890/?t=abc\n") == "http://127.0.0.1:17890/?t=abc"
    assert ha.parse_url("没有网址") is None


def test_launch_happy_path(tmp_path, home):
    ticket, data = build_ticket(tmp_path)
    run = Recorder()
    r = launch(ticket, data, run)
    assert r["ok"] is True and r["url"] == "http://127.0.0.1:17890/?t=abc" and r["version"] == "0.6.1"
    cmd = run.started()[0]
    kw = [k for c, k in run.calls if "start" in c][0]
    assert cmd[0] == "node" and cmd[1].endswith("workbench.mjs") and cmd[2:] == ["start", "--open"]
    assert kw["cwd"] == str(home / "apps" / "xhs-workbench" / "0.6.1")
    assert kw["env"]["HUB_MCP_SERVERS_FILE"] == str(home / "hub-mcp.json") and "HUB_TRACE_ID" in kw["env"]
    assert kw["env"]["HUB_WORK_OUTBOX"] == str(home / "outbox" / "xhs-workbench.jsonl") and (home / "outbox").is_dir()   # 应用把成果写到这里
    # 应用根目录的约定：数据在根目录下（agent 可读写），访问锁等状态在根目录之外（HOME 下），运行错误写 logs/health-<应用>.jsonl
    assert kw["env"]["HUB_APP_DATA_DIR"] == str(home / "data" / "xhs-workbench")
    assert kw["env"]["HUB_APP_STATE_DIR"] == str(home / "state" / "xhs-workbench")
    assert kw["env"]["HUB_HEALTH_OUTBOX"] == str(home / "logs" / "health-xhs-workbench.jsonl")
    assert kw["env"]["HUB_DEVICE_ID"] == ha.device_id() and len(kw["env"]["HUB_DEVICE_ID"]) == 32
    assert any(c[2:] == ["setup"] for c, _ in run.calls)                      # 先 setup 再 start
    cfg = json.loads((home / "hub-mcp.json").read_text(encoding="utf-8"))["mcpServers"]["enterprise-hub"]
    assert cfg["command"] == "/usr/bin/uv" and "--nested" in cfg["args"] and cfg["args"][:1] == ["run"]
    assert (home / "apps" / "xhs-workbench" / "0.6.1" / ".sha256").read_text() == ticket["sha256"]
    assert "SKILL.md" in r["message"]                                         # 告诉 agent 技能路径，收件箱模式据此进入值守


def test_unconfigured_bridge_tells_agent_to_run_connection_selftest(tmp_path, home):
    """工作台网页显示「未连接 agent」就是因为没做连接自检：setup 报告尚未配置时，打开结果必须让 agent 去做。"""
    ticket, data = build_ticket(tmp_path)
    r = launch(ticket, data, Recorder(setup_out="连接配置：尚未配置\n"))
    assert r["ok"] and "连接自检" in r["message"] and "bridge-test" in r["message"]
    ok = launch(ticket, data, Recorder(setup_out="连接配置：收件箱模式\n"))
    assert "连接自检" not in ok["message"]


def test_node_missing_stops_before_download(tmp_path, home):
    ticket, data = build_ticket(tmp_path)
    called = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: called.append(1) or httpx.Response(200, content=data)))

    def run(cmd, **kw):
        raise FileNotFoundError()
    r = ha.launch_app(ticket, "http://hub", {"access_token": "t"}, run=run, client=client)
    assert r["ok"] is False and "Node.js" in r["reason"] and called == []


def test_hash_mismatch_refuses_and_leaves_nothing(tmp_path, home):
    ticket, data = build_ticket(tmp_path)
    ticket["sha256"] = "0" * 64
    run = Recorder()
    r = launch(ticket, data, run)
    assert r["ok"] is False and "校验失败" in r["reason"] and run.started() == []
    assert not (home / "apps" / "xhs-workbench" / "0.6.1").exists()


def test_same_version_same_hash_is_not_downloaded_again(tmp_path, home):
    ticket, data = build_ticket(tmp_path)
    launch(ticket, data, Recorder())
    hits = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: hits.append(1) or httpx.Response(200, content=data)))
    r = ha.launch_app(ticket, "http://hub", {"access_token": "t"}, run=Recorder(), client=client)
    assert r["ok"] and hits == []


def test_republished_same_version_with_new_hash_is_redownloaded(tmp_path, home):
    t1, d1 = build_ticket(tmp_path, payload="old")
    launch(t1, d1, Recorder())
    t2, d2 = build_ticket(tmp_path, payload="new")                           # 同版本号、内容变了
    r = launch(t2, d2, Recorder())
    assert r["ok"] and (home / "apps" / "xhs-workbench" / "0.6.1" / ENTRY).read_text() == "new"


def test_no_url_in_output_reports_reason(tmp_path, home):
    ticket, data = build_ticket(tmp_path)
    r = launch(ticket, data, Recorder(start_out="出错了：端口被占用\n"))
    assert r["ok"] is False and "端口被占用" in r["reason"]


def test_start_timeout_reports_reason(tmp_path, home):
    ticket, data = build_ticket(tmp_path)
    r = launch(ticket, data, Recorder(hang=True))
    assert r["ok"] is False and "超时" in r["reason"]


def test_entry_must_stay_inside_package(tmp_path, home):
    ticket, data = build_ticket(tmp_path, entry="../../etc/evil.mjs")
    run = Recorder()
    r = launch(ticket, data, run)
    assert r["ok"] is False and "入口" in r["reason"] and run.started() == []


def test_running_instance_of_older_version_is_not_restarted(tmp_path, home):
    t1, d1 = build_ticket(tmp_path, version="0.6.0", payload="a")
    launch(t1, d1, Recorder())                                                # 0.6.0 刚启动
    t2, d2 = build_ticket(tmp_path, version="0.6.1", payload="b")
    run = Recorder(start_out="工作台已在运行。\nURL: http://127.0.0.1:17890/?t=abc\n")
    r = launch(t2, d2, run)
    assert r["ok"] and "0.6.1" in r["message"] and "关闭" in r["message"] and "升级" in r["message"]
    assert not any("stop" in c for c, _ in run.calls)                         # 绝不 stop / 重启


def test_concurrent_opens_download_and_extract_once(tmp_path, home, monkeypatch):
    ticket, data = build_ticket(tmp_path)
    extracted, results = [], []
    real = ha.safe_extract
    monkeypatch.setattr(ha, "safe_extract", lambda *a, **k: extracted.append(1) or real(*a, **k))
    ts = [threading.Thread(target=lambda: results.append(launch(ticket, data, Recorder()))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(results) == 3 and all(r["ok"] for r in results) and extracted == [1]


def test_old_versions_are_pruned_after_success(tmp_path, home):
    for v in ("0.5.0", "0.6.0", "0.6.1"):
        t, d = build_ticket(tmp_path, version=v, payload=v)
        launch(t, d, Recorder())
    names = sorted(p.name for p in (home / "apps" / "xhs-workbench").iterdir() if p.is_dir() and not p.name.startswith("."))
    assert len(names) <= 2 and "0.6.1" in names


# ================= 嵌套模式 =================

def test_bridge_headers_use_inherited_trace_id(monkeypatch):
    monkeypatch.setenv("HUB_TRACE_ID", "tr-from-open-app")
    assert ha.bridge_headers()["X-Hub-Trace-Id"] == "tr-from-open-app"
    monkeypatch.delenv("HUB_TRACE_ID")
    assert ha.bridge_headers()["X-Hub-Trace-Id"].startswith("tr-")


def test_nested_bridge_skips_sync_and_heartbeat(monkeypatch):
    import argparse
    calls = {"sync": 0, "threads": 0}
    monkeypatch.setattr(ha, "cmd_sync", lambda *a, **k: calls.__setitem__("sync", calls["sync"] + 1))
    monkeypatch.setattr(ha.threading, "Thread", lambda *a, **k: calls.__setitem__("threads", calls["threads"] + 1) or type("T", (), {"start": lambda s: None})())
    monkeypatch.setattr(ha, "fresh_creds", lambda: {"hub": "http://hub", "access_token": "t"})
    monkeypatch.setattr(ha.httpx, "get", lambda *a, **k: type("R", (), {"json": lambda s: {"mcp_url": "http://hub/mcp"}})())
    monkeypatch.setattr(ha.sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"")})())
    ha.cmd_mcp(argparse.Namespace(client="工作台", nested=True))
    assert calls == {"sync": 0, "threads": 0}
    ha.cmd_mcp(argparse.Namespace(client="WorkBuddy", nested=False))
    assert calls == {"sync": 1, "threads": 2}  # 心跳 + 成果转发


# ================= 桥拦截 open_app =================

def mcp_result(text, rid=7, is_error=False):
    return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}


CALL = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "open_app", "arguments": {"app_id": "xhs-workbench"}}}
HUB_TICKET = {"app_id": "xhs-workbench", "version": "0.6.1", "sha256": "a" * 64, "download_url": "http://hub/dl", "entry": ENTRY,
              "requires": {}, "start_args": [], "needs_local_connector": True}


def intercept(msg, resp_msgs, result):
    seen = []

    def fake_launch(ticket, hub, creds, **kw):
        seen.append(ticket)
        return result
    out = ha.bridge_intercept(msg, resp_msgs, fake_launch, hub="http://hub", creds={"access_token": "t"},
                              report=lambda *a, **k: seen.append("reported"))
    return out, seen


def test_intercept_replaces_ticket_with_launch_result():
    out, seen = intercept(CALL, [mcp_result(json.dumps(HUB_TICKET))], {"ok": True, "url": "http://127.0.0.1:17890/?t=x", "message": "已打开：http://127.0.0.1:17890/?t=x", "version": "0.6.1"})
    assert len(out) == 1 and out[0]["id"] == 7 and out[0]["result"]["isError"] is False
    assert "http://127.0.0.1:17890/?t=x" in out[0]["result"]["content"][0]["text"]
    # open_app 在中枢声明了输出 schema：替换后的回复必须同样带 structuredContent，否则客户端报 "has an output schema but did not return structured content"
    assert out[0]["result"]["structuredContent"] == {"result": out[0]["result"]["content"][0]["text"]}
    assert seen[0]["app_id"] == "xhs-workbench" and seen[-1] == "reported"        # 启动后回报中枢


def test_intercept_launch_failure_is_an_error_with_reason():
    out, seen = intercept(CALL, [mcp_result(json.dumps(HUB_TICKET))], {"ok": False, "reason": "缺少 Node.js 18"})
    assert out[0]["result"]["isError"] is True and "缺少 Node.js 18" in out[0]["result"]["content"][0]["text"]


def test_intercept_passes_hub_refusal_through_untouched():
    refusal = [mcp_result("岗位包「财务」没有打开「小红书运营工作台」的权限。该请求已记录。")]
    out, seen = intercept(CALL, refusal, {"ok": True})
    assert out == refusal and seen == []                                            # 不启动、不回报、原样透传


def test_intercept_ignores_other_calls_and_errors():
    other = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_knowledge", "arguments": {}}}
    assert intercept(other, [mcp_result("{}")], {"ok": True})[0] is None
    assert intercept({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, [], {"ok": True})[0] is None
    err = [{"jsonrpc": "2.0", "id": 7, "error": {"code": -32603, "message": "中枢不可用"}}]
    assert intercept(CALL, err, {"ok": True})[0] == err                               # 中枢返回协议错误：原样透传


def test_parse_response_handles_json_and_sse():
    body = json.dumps(mcp_result("hi"))
    r_json = httpx.Response(200, content=body.encode(), headers={"content-type": "application/json"})
    r_sse = httpx.Response(200, content=f"event: message\ndata: {body}\n\n".encode(), headers={"content-type": "text/event-stream"})
    assert ha.parse_response(r_json) == ha.parse_response(r_sse) == [mcp_result("hi")]
    assert ha.parse_response(httpx.Response(202)) == []



# ---------------- 应用根目录（~/HubApps） ----------------

def test_apps_base_keeps_legacy_installs_and_uses_root_for_new(tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "HOME", tmp_path / "hub-agent")
    monkeypatch.setattr(ha, "HUB_APPS", tmp_path / "HubApps")
    assert ha.app_dir("xhs-workbench", "0.7.9") == tmp_path / "HubApps" / "apps" / "xhs-workbench" / "0.7.9"  # 新装
    (tmp_path / "hub-agent" / "apps" / "xhs-workbench" / "0.7.5").mkdir(parents=True)
    assert ha.apps_base() == tmp_path / "hub-agent" / "apps"  # 已经在旧位置装过：保持不动


def test_runtime_node_preferred_and_put_first_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "HUB_APPS", tmp_path)
    assert ha.node_bin() == "node" and ha.with_runtime_path({"PATH": "x"}) == {"PATH": "x"}
    node_dir = tmp_path / "runtime" / "node" if ha.sys.platform == "win32" else tmp_path / "runtime" / "node" / "bin"
    node_dir.mkdir(parents=True)
    (node_dir / ("node.exe" if ha.sys.platform == "win32" else "node")).write_text("")
    assert ha.node_bin().startswith(str(node_dir))
    assert ha.with_runtime_path({"PATH": "x"})["PATH"].split(ha.os.pathsep) == [str(node_dir), "x"]


def test_register_app_root_in_workbuddy_and_codebuddy(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(ha.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(ha, "HUB_APPS", home / "HubApps")
    wb = home / ".workbuddy" / "settings.json"
    wb.parent.mkdir(parents=True)
    wb.write_text(json.dumps({"sandbox": {"extraAllowWrite": ["~/.lark-cli"], "other": 1}, "keep": True}), encoding="utf-8")
    cb = home / ".codebuddy"
    cb.mkdir()
    r = dict(ha.register_app_root(wb, cb))
    assert "已把 ~/HubApps/" in r["WorkBuddy 目录权限"] and "已把" in r["CodeBuddy CLI 目录权限"]
    d = json.loads(wb.read_text(encoding="utf-8"))
    assert d["sandbox"]["extraAllowWrite"] == ["~/.lark-cli", "~/HubApps/"] and d["sandbox"]["other"] == 1 and d["keep"] is True
    assert json.loads((cb / "settings.json").read_text(encoding="utf-8"))["permissions"]["additionalDirectories"] == [str(home / "HubApps")]
    assert list(wb.parent.glob("settings.json.bak-hub-*"))  # 改之前备份
    assert dict(ha.register_app_root(wb, cb)) == {"WorkBuddy 目录权限": "已登记", "CodeBuddy CLI 目录权限": "已登记"}  # 幂等
    wb.write_text("{坏的", encoding="utf-8")
    assert "格式有误" in dict(ha.register_app_root(wb, cb))["WorkBuddy 目录权限"] and wb.read_text(encoding="utf-8") == "{坏的"
    # 没装的 agent 不碰
    assert ha.register_app_root(tmp_path / "none" / "settings.json", tmp_path / "none-cb") == []


def test_write_launchers(tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "HUB_APPS", tmp_path)
    made = ha.write_launchers([{"id": "xhs-workbench", "name": "小红书运营工作台"}, {"id": "../bad", "name": "x"}], uv="C:/uv/uv.exe", script="C:/a/hub_agent.py")
    assert [m["id"] for m in made] == ["xhs-workbench"]
    f = ha.Path(made[0]["path"])
    text = f.read_bytes().decode("utf-8")
    assert "open-app xhs-workbench --browser" in text and '"C:/uv/uv.exe" run "C:/a/hub_agent.py"' in text
    if ha.sys.platform == "win32":
        assert text.startswith("@echo off\r\n") and "\r\r\n" not in text
    assert json.loads((tmp_path / "bin" / "launchers.json").read_text(encoding="utf-8"))[0]["name"] == "小红书运营工作台"
