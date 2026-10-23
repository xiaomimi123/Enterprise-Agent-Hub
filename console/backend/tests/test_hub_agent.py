"""员工端接入器（agent/hub_agent.py）：岗位包技能同步到 WorkBuddy 的技能目录。"""

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("hub_agent", Path(__file__).resolve().parents[3] / "agent" / "hub_agent.py")
hub_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hub_agent)

SKILL = "---\nname: 标题与正文撰写\ndescription: 按品牌人设写小红书标题和正文\n---\n\n# 标题与正文撰写\n步骤……\n"


def cfg(*ids):
    return {"employee": {"name": "周一诺", "role_pack": "小红书运营"},
            "skills": [{"id": i, "name": i, "description": f"{i} 的说明", "content": SKILL} for i in ids]}


@pytest.fixture
def wb(tmp_path):
    skills = tmp_path / ".workbuddy" / "skills"
    skills.mkdir(parents=True)
    (skills / "capcut").mkdir()                       # 员工自己装的技能
    (skills / "capcut" / "SKILL.md").write_text("mine", encoding="utf-8")
    (skills / "hub-mine").mkdir()                     # 前缀相同但不是中枢下发的（没有标记）
    (skills / "hub-mine" / "SKILL.md").write_text("mine too", encoding="utf-8")
    return skills


def test_writes_pack_skills_with_marker_and_banner(wb):
    n = hub_agent.sync_workbuddy_skills(cfg("xhs-writing", "xhs-cover"), wb)
    assert n == 2
    text = (wb / "hub-xhs-writing" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: 标题与正文撰写\n")          # frontmatter 仍在最前面，WorkBuddy 才能识别
    assert "enterprise-hub" in text and "小红书运营" in text      # 说明来源和调用方式
    assert (wb / "hub-xhs-writing" / hub_agent.WB_MARKER).exists()
    guide = (wb / "hub-guide" / "SKILL.md").read_text(encoding="utf-8")
    assert guide.startswith("---\n") and "search_knowledge" in guide and "周一诺" in guide


def test_resync_removes_revoked_skills_but_not_users_own(wb):
    hub_agent.sync_workbuddy_skills(cfg("xhs-writing", "xhs-cover"), wb)
    hub_agent.sync_workbuddy_skills(cfg("xhs-writing"), wb)      # 岗位包撤掉了 xhs-cover
    names = {p.name for p in wb.iterdir()}
    assert "hub-xhs-cover" not in names
    assert {"hub-xhs-writing", "hub-guide", "capcut", "hub-mine"} <= names
    assert (wb / "hub-mine" / "SKILL.md").read_text(encoding="utf-8") == "mine too"


def test_skips_when_workbuddy_not_installed(tmp_path):
    assert hub_agent.sync_workbuddy_skills(cfg("xhs-writing"), tmp_path / ".workbuddy" / "skills") is None
    assert not (tmp_path / ".workbuddy").exists()


def test_bridge_mode_keeps_stdout_clean(capsys):
    hub_agent.log_to_stderr()
    try:
        hub_agent.info("同步完成")
    finally:
        hub_agent.log_to_stderr(False)
    out = capsys.readouterr()
    assert out.out == "" and "同步完成" in out.err


# ---- 一键接入：自动把中枢写进已安装 agent 的 MCP 配置 ----

import json  # noqa: E402


def clients(tmp_path):
    return [
        {"name": "WorkBuddy", "detect": tmp_path / ".workbuddy", "config": tmp_path / ".workbuddy" / "mcp.json"},
        {"name": "Cursor", "detect": tmp_path / ".cursor", "config": tmp_path / ".cursor" / "mcp.json"},
        {"name": "Claude 桌面版", "detect": tmp_path / "Claude", "config": tmp_path / "Claude" / "claude_desktop_config.json"},
    ]


def test_configure_merges_backs_up_and_skips_missing(tmp_path):
    (tmp_path / ".workbuddy").mkdir()
    (tmp_path / ".workbuddy" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"mine": {"command": "x"}}, "other": 1}), encoding="utf-8")
    (tmp_path / ".cursor").mkdir()                              # 装了 Cursor 但还没有配置文件
    res = dict(hub_agent.configure_agents(clients(tmp_path), "C:/uv.exe", "C:/a/hub_agent.py"))
    assert res == {"WorkBuddy": "已配置", "Cursor": "已配置", "Claude 桌面版": "未安装"}
    wb = json.loads((tmp_path / ".workbuddy" / "mcp.json").read_text(encoding="utf-8"))
    assert wb["mcpServers"]["mine"] == {"command": "x"} and wb["other"] == 1      # 原有内容保留
    assert wb["mcpServers"]["enterprise-hub"]["args"] == ["run", "C:/a/hub_agent.py", "mcp", "--client", "WorkBuddy"]
    assert wb["mcpServers"]["enterprise-hub"]["command"] == "C:/uv.exe"
    assert len(list((tmp_path / ".workbuddy").glob("mcp.json.bak-hub-*"))) == 1    # 改之前备份
    assert "enterprise-hub" in json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert not (tmp_path / "Claude").exists()


def test_configure_is_idempotent(tmp_path):
    (tmp_path / ".workbuddy").mkdir()
    hub_agent.configure_agents(clients(tmp_path), "uv", "s.py")
    assert dict(hub_agent.configure_agents(clients(tmp_path), "uv", "s.py"))["WorkBuddy"] == "已是最新"
    assert list((tmp_path / ".workbuddy").glob("*.bak-hub-*")) == []          # 第一次没有原文件，第二次没改动


def test_configure_never_overwrites_broken_config(tmp_path):
    (tmp_path / ".workbuddy").mkdir()
    (tmp_path / ".workbuddy" / "mcp.json").write_text("{not json", encoding="utf-8")
    status = dict(hub_agent.configure_agents(clients(tmp_path), "uv", "s.py"))["WorkBuddy"]
    assert "格式" in status
    assert (tmp_path / ".workbuddy" / "mcp.json").read_text(encoding="utf-8") == "{not json"


def test_configure_reads_config_with_utf8_bom(tmp_path):
    (tmp_path / ".workbuddy").mkdir()
    (tmp_path / ".workbuddy" / "mcp.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": {"mine": {}}}).encode())
    assert dict(hub_agent.configure_agents(clients(tmp_path), "uv", "s.py"))["WorkBuddy"] == "已配置"
    assert "mine" in json.loads((tmp_path / ".workbuddy" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]


def test_configure_passes_client_name_and_heartbeat_payload(tmp_path):
    (tmp_path / ".workbuddy").mkdir()
    hub_agent.configure_agents(clients(tmp_path), "uv", "s.py")
    args = json.loads((tmp_path / ".workbuddy" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["enterprise-hub"]["args"]
    assert args == ["run", "s.py", "mcp", "--client", "WorkBuddy"]
    p = hub_agent.heartbeat_payload("WorkBuddy")
    assert p["client"] == "WorkBuddy" and p["version"] == hub_agent.VERSION and p["os"]


def test_chat_syncs_with_session_key_scope_but_plain_sync_does_not(monkeypatch):
    seen = []

    class R:
        status_code = 200

        def json(self):
            return {"employee": {"name": "U", "user": "u", "role_pack": "p"}, "mcp_url": "http://m", "model": None,
                    "skills": [], "max_action_level": "需确认"}
    monkeypatch.setattr(hub_agent, "fresh_creds", lambda: {"hub": "http://hub", "access_token": "t"})
    monkeypatch.setattr(hub_agent.httpx, "post", lambda url, **kw: seen.append(kw["headers"]) or R())
    monkeypatch.setattr(hub_agent, "sync_workbuddy_skills", lambda cfg, root=None: None)
    monkeypatch.setattr(hub_agent, "write_private", lambda *a, **k: None)
    monkeypatch.setattr(hub_agent.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(hub_agent.Path, "mkdir", lambda *a, **k: None)
    monkeypatch.setattr(hub_agent.Path, "write_text", lambda *a, **k: None)
    hub_agent.cmd_sync(trace_id="tr-chat", session_key=True)
    hub_agent.cmd_sync(trace_id="tr-plain")
    assert seen[0]["X-Hub-Key-Scope"] == "session" and seen[0]["X-Hub-Trace-Id"] == "tr-chat"
    assert "X-Hub-Key-Scope" not in seen[1]


# ---- CodeBuddy CLI：中枢模型写进 models.json、MCP 写进 .mcp.json ----

def model_cfg(models=("deepseek-v4", "qwen-max")):
    return {"employee": {"name": "周一诺", "role_pack": "小红书运营"}, "skills": [],
            "model": {"base_url": "http://hub:3000/v1", "api_key": "sk-employee-key", "model": models[0], "models": list(models)}}


def test_codebuddy_models_written_with_full_chat_completions_url_and_default(tmp_path):
    home, state = tmp_path / ".codebuddy", tmp_path / "state.json"
    home.mkdir()
    (home / "models.json").write_text(json.dumps({"models": [{"id": "mine", "name": "我的模型", "url": "http://x/v1/chat/completions"}],
                                                  "availableModels": ["mine"]}), encoding="utf-8")
    msg = hub_agent.sync_codebuddy_models(model_cfg(), home, state)
    data = json.loads((home / "models.json").read_text(encoding="utf-8"))
    ours = [m for m in data["models"] if m["name"].startswith(hub_agent.CB_MODEL_PREFIX)]
    assert [m["id"] for m in ours] == ["deepseek-v4", "qwen-max"] and "2 个" in msg
    assert all(m["url"] == "http://hub:3000/v1/chat/completions" and m["apiKey"] == "sk-employee-key" and m["supportsToolCall"] for m in ours)
    assert data["availableModels"] == ["mine"] and any(m["id"] == "mine" for m in data["models"])   # 员工自己的模型和设置保留
    st = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert st["model"] == "deepseek-v4" and st["permissions"]["allow"] == ["DeferExecuteTool"]                # 无人值守也能调中枢工具
    assert list(home.glob("models.json.bak-hub-*"))                                                    # 改之前备份


def test_codebuddy_sync_is_idempotent_updates_key_and_respects_user_default(tmp_path):
    home, state = tmp_path / ".codebuddy", tmp_path / "state.json"
    home.mkdir()
    hub_agent.sync_codebuddy_models(model_cfg(), home, state)
    c2 = model_cfg()
    c2["model"]["api_key"] = "sk-rotated"
    hub_agent.sync_codebuddy_models(c2, home, state)
    data = json.loads((home / "models.json").read_text(encoding="utf-8"))
    assert [m["apiKey"] for m in data["models"]] == ["sk-rotated", "sk-rotated"] and len(data["models"]) == 2   # 不重复追加
    s = home / "settings.json"
    s.write_text(json.dumps({"model": "my-own-choice", "env": {"A": "1"}, "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(.env)"]}}),
                 encoding="utf-8")                                                                           # 员工自己改了默认模型、有自己的权限规则
    hub_agent.sync_codebuddy_models(c2, home, state)
    st = json.loads(s.read_text(encoding="utf-8"))
    assert st["model"] == "my-own-choice" and st["env"] == {"A": "1"} and st["permissions"]["deny"] == ["Read(.env)"]
    assert st["permissions"]["allow"] == ["Bash(ls)", "DeferExecuteTool"]                                    # 追加而不是覆盖，且不重复
    hub_agent.sync_codebuddy_models(c2, home, state)
    assert json.loads(s.read_text(encoding="utf-8"))["permissions"]["allow"] == ["Bash(ls)", "DeferExecuteTool"]


def test_codebuddy_cleanup_when_no_model_and_skip_when_not_installed_or_broken(tmp_path):
    home, state = tmp_path / ".codebuddy", tmp_path / "state.json"
    assert hub_agent.sync_codebuddy_models(model_cfg(), home, state) is None                                   # 没装
    home.mkdir()
    hub_agent.sync_codebuddy_models(model_cfg(), home, state)
    msg = hub_agent.sync_codebuddy_models({"employee": {}, "skills": []}, home, state)                         # 岗位包改成自带模型
    assert "清理" in msg and json.loads((home / "models.json").read_text(encoding="utf-8"))["models"] == []
    assert "model" not in json.loads((home / "settings.json").read_text(encoding="utf-8"))
    (home / "models.json").write_text("{broken", encoding="utf-8")
    assert "格式有误" in hub_agent.sync_codebuddy_models(model_cfg(), home, state)
    assert (home / "models.json").read_text(encoding="utf-8") == "{broken"                                      # 坏文件不覆盖


def test_codebuddy_mcp_file_precedence(tmp_path):
    home = tmp_path / ".codebuddy"
    home.mkdir()
    assert hub_agent.codebuddy_mcp_file(home) == home / ".mcp.json"                                            # 都没有：新建推荐文件
    (tmp_path / ".codebuddy.json").write_text(json.dumps({"mcpServers": {"old": {"command": "x"}}}), encoding="utf-8")
    assert hub_agent.codebuddy_mcp_file(home) == tmp_path / ".codebuddy.json"                                  # 旧文件里已有服务器：写它，避免顶掉
    (home / "mcp.json").write_text("{}", encoding="utf-8")
    assert hub_agent.codebuddy_mcp_file(home) == home / "mcp.json"
    (home / ".mcp.json").write_text("{}", encoding="utf-8")
    assert hub_agent.codebuddy_mcp_file(home) == home / ".mcp.json"


# ---- 应用能力预检：缺什么说明并询问安装，只让对应能力不可用 ----

REQ = {"node": ">=18", "agent_cli": "codebuddy", "capabilities": ["browser"]}
PROFILE = {"model": {"model": "deepseek-v4-flash", "models": ["deepseek-v4-flash"]}}


def pf(requires=REQ, tools=("codebuddy", "npm", "npx"), browser="C:/Edge/msedge.exe", warm=True, profile=PROFILE, cb_home=None):
    return hub_agent.preflight(requires, which=lambda n: f"/bin/{n}" if n in tools else None, browser_finder=lambda: browser,
                               cached=lambda v: warm, codebuddy_home=cb_home, profile=profile)


def cb_home_with_model(base, default="deepseek-v4-flash", model_id="deepseek-v4-flash"):
    home = base / ".codebuddy"
    home.mkdir(parents=True)
    (home / "models.json").write_text(json.dumps({"models": [{"id": model_id, "name": hub_agent.CB_MODEL_PREFIX + model_id}]}), encoding="utf-8")
    (home / "settings.json").write_text(json.dumps({"model": default}), encoding="utf-8")
    return home


def ids(result):
    return {c["id"]: c for c in result["checks"]}


def test_preflight_all_satisfied(tmp_path):
    r = pf(cb_home=cb_home_with_model(tmp_path))
    assert r["missing"] == [] and r["capabilities"]["browser"]["ready"] and r["capabilities"]["agent_cli"]["ready"]
    assert hub_agent.capability_notice("xhs-workbench", r) == ""


def test_preflight_missing_cli_blocks_browser_with_install_command(tmp_path):
    r = pf(tools=("npm", "npx"), cb_home=cb_home_with_model(tmp_path))
    assert r["missing"] == ["CodeBuddy CLI"] and not r["capabilities"]["browser"]["ready"]
    fix = ids(r)["agent_cli"]["fix"]
    assert fix["argv"][:3] == ["npm", "install", "-g"] and fix["argv"][-1] == "@tencent-ai/codebuddy-code"
    notice = hub_agent.capability_notice("xhs-workbench", r)
    assert "已打开" in notice and "CodeBuddy CLI" in notice and "app-doctor xhs-workbench --yes" in notice and "是否同意" in notice


def test_preflight_without_node_gives_manual_hint_not_an_auto_install(tmp_path):
    r = pf(tools=(), cb_home=cb_home_with_model(tmp_path))
    assert {"CodeBuddy CLI", "npx（运行 Playwright）"} <= set(r["missing"])
    assert ids(r)["agent_cli"]["fix"]["argv"] is None and "Node.js" in ids(r)["agent_cli"]["fix"]["text"]    # 没有 npm 不能自动装
    assert "app-doctor" not in hub_agent.capability_notice("x", r)                                           # 没有可自动装的项就不提示 --yes


def test_preflight_missing_system_browser_is_manual(tmp_path):
    r = pf(browser=None, cb_home=cb_home_with_model(tmp_path))
    assert r["missing"] == ["系统浏览器"] and not r["capabilities"]["browser"]["ready"] and r["capabilities"]["agent_cli"]["ready"]
    assert ids(r)["system_browser"]["fix"]["argv"] is None


def test_preflight_hub_model_must_really_be_configured(tmp_path):
    r = pf(cb_home=cb_home_with_model(tmp_path / "a", model_id="other-model"))     # models.json 里没有中枢下发的模型
    assert "中枢模型" in r["missing"] and not r["capabilities"]["browser"]["ready"]
    assert ids(r)["hub_model"]["fix"]["argv"][-1] == "sync"
    # 默认模型被员工换掉：不拦，但提示可能不走中枢计量
    r = pf(cb_home=cb_home_with_model(tmp_path / "b", default="my-own"))
    assert r["capabilities"]["browser"]["ready"] and ids(r)["hub_model"]["warn"] and "不走中枢计量" in ids(r)["hub_model"]["detail"]
    # 岗位包用自带模型：不检查
    r = pf(profile={}, cb_home=tmp_path / "none")
    assert ids(r)["hub_model"]["ok"] and "自带模型" in ids(r)["hub_model"]["detail"]


def test_preflight_cold_playwright_is_only_a_hint(tmp_path):
    r = pf(warm=False, cb_home=cb_home_with_model(tmp_path / "a"))
    assert r["missing"] == [] and r["capabilities"]["browser"]["ready"] and ids(r)["playwright_mcp"]["warn"]
    assert ids(r)["playwright_mcp"]["fix"]["argv"][:2] == ["npx", "-y"]
    notice = hub_agent.capability_notice("x", r)
    assert "提示" in notice and "首次使用要下载" in notice
    pinned = pf(requires={**REQ, "playwright_mcp": "0.0.83"}, warm=False, cb_home=cb_home_with_model(tmp_path / "b"))
    assert "@playwright/mcp@0.0.83" in ids(pinned)["playwright_mcp"]["fix"]["argv"][2]


def test_apps_without_requirements_are_not_checked():
    r = hub_agent.preflight({"node": ">=18"}, which=lambda n: None, profile={})
    assert r == {"checks": [], "capabilities": {}, "missing": []}


def test_capability_file_has_no_secrets_and_is_readable_by_the_app(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_agent, "CAPABILITIES_DIR", tmp_path / "capabilities")
    f = hub_agent.write_capabilities("xhs-workbench", "0.7.2", pf(tools=("npm", "npx"), profile={"model": {"model": "m", "api_key": "sk-SECRET"}},
                                                                    cb_home=tmp_path / "none"))
    doc = json.loads(f.read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and doc["app_id"] == "xhs-workbench" and doc["version"] == "0.7.2"
    assert doc["capabilities"]["browser"]["ready"] is False and "CodeBuddy CLI" in doc["capabilities"]["browser"]["missing"]
    assert "sk-SECRET" not in f.read_text(encoding="utf-8")


class FakeRun:
    """假的子进程：记录要执行的命令；装 CodeBuddy 成功后，让 which 能找到它。"""

    def __init__(self, tools, ok=True):
        self.calls, self.tools, self.ok = [], tools, ok

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if self.ok and any("@tencent-ai/codebuddy-code" in str(a) for a in argv):
            self.tools.add("codebuddy")
        return type("R", (), {"returncode": 0 if self.ok else 1, "stdout": "added 1 package", "stderr": ""})()


def doctor_env(tmp_path, monkeypatch, requires=REQ, browser="C:/Edge", model=True):
    import argparse
    home = tmp_path / "home"
    monkeypatch.setattr(hub_agent, "HOME", home)
    monkeypatch.setattr(hub_agent, "CAPABILITIES_DIR", home / "capabilities")
    (home / "apps" / "demo").mkdir(parents=True)
    (home / "apps" / "demo" / ".requires.json").write_text(json.dumps({"requires": requires, "version": "1"}), encoding="utf-8")
    if model:
        (home / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
        monkeypatch.setattr(hub_agent, "CODEBUDDY_HOME", cb_home_with_model(tmp_path))
    tools = {"npm", "npx"}
    monkeypatch.setattr(hub_agent.shutil, "which", lambda n: f"/bin/{n}" if n in tools else None)
    monkeypatch.setattr(hub_agent, "find_system_browser", lambda *a, **k: browser)
    monkeypatch.setattr(hub_agent, "playwright_cached", lambda v=None, **k: True)
    ns = lambda yes=False: argparse.Namespace(app_id="demo", yes=yes)  # noqa: E731
    cap = lambda: json.loads((home / "capabilities" / "demo.json").read_text(encoding="utf-8"))  # noqa: E731
    return tools, ns, cap


def test_doctor_asks_before_installing_and_respects_no(tmp_path, monkeypatch):
    tools, ns, cap = doctor_env(tmp_path, monkeypatch)
    asked, run = [], FakeRun(tools)
    hub_agent.cmd_app_doctor(ns(), ask=lambda q: asked.append(q) or False, run=run)
    assert run.calls == [] and len(asked) == 1 and "codebuddy-code" in asked[0]                 # 问了，员工说不，就不装
    assert cap()["capabilities"]["browser"]["ready"] is False


def test_doctor_installs_after_consent_and_refreshes_capability_file(tmp_path, monkeypatch):
    tools, ns, cap = doctor_env(tmp_path, monkeypatch)
    run = FakeRun(tools)
    hub_agent.cmd_app_doctor(ns(), ask=lambda q: True, run=run)
    assert any("@tencent-ai/codebuddy-code" in str(c) for c in run.calls)
    assert cap()["capabilities"]["browser"]["ready"] is True and cap()["capabilities"]["browser"]["missing"] == []   # 装好后能力文件已刷新


def test_doctor_yes_flag_means_consent_already_given(tmp_path, monkeypatch):
    tools, ns, cap = doctor_env(tmp_path, monkeypatch)
    asked, run = [], FakeRun(tools)
    hub_agent.cmd_app_doctor(ns(yes=True), ask=lambda q: asked.append(q) or False, run=run)
    assert asked == [] and any("@tencent-ai/codebuddy-code" in str(c) for c in run.calls)


def test_doctor_failed_install_is_reported_not_hidden(tmp_path, monkeypatch, capsys):
    tools, ns, cap = doctor_env(tmp_path, monkeypatch)
    hub_agent.cmd_app_doctor(ns(yes=True), run=FakeRun(tools, ok=False))
    assert "失败" in capsys.readouterr().out and cap()["capabilities"]["browser"]["ready"] is False


def test_doctor_never_runs_manual_only_fixes_even_with_yes(tmp_path, monkeypatch):
    tools, ns, cap = doctor_env(tmp_path, monkeypatch, browser=None)
    tools.add("codebuddy")
    run = FakeRun(tools)
    hub_agent.cmd_app_doctor(ns(yes=True), run=run)
    assert run.calls == []                                                                       # 系统浏览器只能手动装，不会被执行
    assert cap()["capabilities"]["browser"]["missing"] == ["系统浏览器"]


def test_doctor_needs_a_previous_open(tmp_path, monkeypatch):
    import argparse
    monkeypatch.setattr(hub_agent, "HOME", tmp_path / "empty")
    with pytest.raises(SystemExit):
        hub_agent.cmd_app_doctor(argparse.Namespace(app_id="never-opened", yes=True))


def test_find_system_browser_per_platform():
    assert hub_agent.find_system_browser("win32", exists=lambda p: p.endswith("msedge.exe"), env={"ProgramFiles(x86)": "C:/PF86"}).endswith("msedge.exe")
    assert hub_agent.find_system_browser("win32", exists=lambda p: False, env={"ProgramFiles": "C:/PF"}) is None
    assert hub_agent.find_system_browser("darwin", exists=lambda p: "Chrome" in p) == "/Applications/Google Chrome.app"
    assert hub_agent.find_system_browser("linux", which=lambda n: "/usr/bin/chromium" if n == "chromium" else None) == "/usr/bin/chromium"
    assert hub_agent.find_system_browser("linux", which=lambda n: None) is None


# ---- 应用成果自动上报（outbox）----

class FakePost:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def __call__(self, app_id, items):
        self.calls.append((app_id, items))
        return type("R", (), {"status_code": self.status})()


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_agent, "OUTBOX_DIR", tmp_path / "outbox")
    (tmp_path / "outbox").mkdir()
    return tmp_path / "outbox"


def line(key, title="笔记A", **kw):
    return json.dumps({"key": key, "title": title, **kw}, ensure_ascii=False) + "\n"


def test_outbox_forwards_new_lines_once_and_remembers_offset(outbox):
    f = outbox / "xhs-workbench.jsonl"
    f.write_text(line("note:1") + line("note:2", status="待审核"), encoding="utf-8")
    post = FakePost()
    assert hub_agent.flush_outbox({}, "h", post=post) == 2
    assert [i["key"] for i in post.calls[0][1]] == ["note:1", "note:2"] and post.calls[0][0] == "xhs-workbench"
    assert hub_agent.flush_outbox({}, "h", post=post) == 0 and len(post.calls) == 1            # 没有新内容不重复发
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line("note:3"))
    assert hub_agent.flush_outbox({}, "h", post=post) == 1 and post.calls[1][1][0]["key"] == "note:3"


def test_outbox_leaves_a_half_written_last_line_for_next_time(outbox):
    f = outbox / "demo.jsonl"
    f.write_bytes((line("a") + '{"key": "b", "ti').encode("utf-8"))
    post = FakePost()
    assert hub_agent.flush_outbox({}, "h", post=post) == 1
    with f.open("ab") as fh:
        fh.write('tle": "写完了"}\n'.encode("utf-8"))
    assert hub_agent.flush_outbox({}, "h", post=post) == 1 and post.calls[1][1][0]["title"] == "写完了"


def test_outbox_drops_bad_lines_and_unknown_fields(outbox):
    (outbox / "demo.jsonl").write_text("not json\n" + line("a", secret="x", token="t", status="已完成") + '{"title":"无key"}\n' + "x" * 5000 + "\n", encoding="utf-8")
    post = FakePost()
    assert hub_agent.flush_outbox({}, "h", post=post) == 1
    assert post.calls[0][1] == [{"key": "a", "title": "笔记A", "status": "已完成"}]


def test_outbox_retries_when_hub_is_down_but_skips_rejected_batches(outbox):
    f = outbox / "demo.jsonl"
    f.write_text(line("a"), encoding="utf-8")
    assert hub_agent.flush_outbox({}, "h", post=FakePost(503)) == 0
    assert hub_agent.flush_outbox({}, "h", post=FakePost(200)) == 1                            # 之前失败，偏移没动，这次补发
    f.write_text(f.read_text(encoding="utf-8") + line("b"), encoding="utf-8")
    assert hub_agent.flush_outbox({}, "h", post=FakePost(400)) == 0                            # 400：这批有问题，跳过不卡住
    assert hub_agent.flush_outbox({}, "h", post=FakePost(200)) == 0

    def boom(app_id, items):
        raise OSError("断网")
    f.write_text(f.read_text(encoding="utf-8") + line("c"), encoding="utf-8")
    assert hub_agent.flush_outbox({}, "h", post=boom) == 0
    assert hub_agent.flush_outbox({}, "h", post=FakePost(200)) == 1


def test_outbox_restarts_from_the_top_if_file_was_replaced_and_ignores_bad_names(outbox):
    f = outbox / "demo.jsonl"
    f.write_text(line("a") + line("b"), encoding="utf-8")
    hub_agent.flush_outbox({}, "h", post=FakePost())
    f.write_text(line("c"), encoding="utf-8")                                                  # 比偏移短：当作被清空重写
    post = FakePost()
    assert hub_agent.flush_outbox({}, "h", post=post) == 1 and post.calls[0][1][0]["key"] == "c"
    (outbox / "Bad Name.jsonl").write_text(line("x"), encoding="utf-8")
    assert hub_agent.flush_outbox({}, "h", post=FakePost()) == 0


def test_outbox_batches_of_fifty(outbox):
    (outbox / "demo.jsonl").write_text("".join(line(f"k{i}") for i in range(120)), encoding="utf-8")
    post = FakePost()
    assert hub_agent.flush_outbox({}, "h", post=post) == 120 and [len(c[1]) for c in post.calls] == [50, 50, 20]


def test_browser_login_survives_browser_preconnects(monkeypatch):
    """回归：Edge / Chrome 打开授权页时会预连接回调地址。旧实现是单线程只服务一次，空闲的预连接占住唯一的处理线程，
    真正的回调排在后面永远得不到应答，页面一直转圈（真实员工电脑上踩过）。"""
    import socket
    import threading
    import urllib.parse as up

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(hub_agent, "CALLBACK_PORT", port)
    monkeypatch.setattr(hub_agent, "LOGIN_WAIT_SECONDS", 8)
    seen = {}

    def fake_open(url):
        state = up.parse_qs(up.urlparse(url).query)["state"][0]

        def run():
            idle = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(4)]  # 只连不发请求
            import httpx
            seen["favicon"] = httpx.get(f"http://127.0.0.1:{port}/favicon.ico", timeout=10).status_code
            seen["callback"] = httpx.get(f"http://127.0.0.1:{port}/callback?code=C1&state={state}", timeout=10).status_code
            for c in idle:
                c.close()

        threading.Thread(target=run, daemon=True).start()

    class Resp:
        def json(self):
            return {"access_token": "tok"}

    monkeypatch.setattr(hub_agent.webbrowser, "open", fake_open)
    monkeypatch.setattr(hub_agent.httpx, "post", lambda *a, **k: Resp())
    tok = hub_agent.browser_login("http://hub", {"casdoor_url": "http://cas", "client_id": "cid", "redirect_uri": f"http://127.0.0.1:{port}/callback"})
    assert tok["access_token"] == "tok" and seen["callback"] == 200 and seen["favicon"] == 200   # favicon 不会被当成回调结果


# ---------------- 应用健康：本机事件队列 ----------------

@pytest.fixture
def health_home(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_agent, "HOME", tmp_path / "hub-agent")
    monkeypatch.setattr(hub_agent, "HUB_APPS", tmp_path / "HubApps")
    monkeypatch.delenv("HUB_HEALTH", raising=False)
    return tmp_path


def _events(root):
    f = root / "HubApps" / "logs" / "health.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def test_health_record_redacts_classifies_and_dedupes(health_home):
    assert hub_agent.record_health("login", False, None, "连不上中枢 http://192.168.0.41:8088：ConnectError C:\\Users\\张三\\x token=abc", now=1000.0)
    assert not hub_agent.record_health("login", False, None, "连不上中枢 http://192.168.0.41:8088：ConnectError C:\\Users\\张三\\x token=abc", now=1100.0)  # 10 分钟内同一错误只记一次
    assert hub_agent.record_health("login", False, None, "连不上中枢 http://192.168.0.41:8088：ConnectError C:\\Users\\张三\\x token=abc", now=1000.0 + 601)
    assert hub_agent.record_health("launch", True, app_id="xhs-workbench", app_version="0.7.9", now=1700.0)
    evs = _events(health_home)
    assert len(evs) == 3
    e = evs[0]
    assert e["code"] == "NET_UNREACHABLE" and "张三" not in e["message"] and "abc" not in e["message"] and "~\\x" in e["message"]
    assert e["device_id"] == evs[2]["device_id"] and len(e["device_id"]) == 32  # 本机固定的随机设备号
    assert evs[2] == {**evs[2], "ok": True, "code": "OK", "message": "", "app_id": "xhs-workbench"}
    assert {"os", "os_version", "arch", "connector_version", "agent", "at"} <= set(e)


def test_health_off_switch(health_home, monkeypatch):
    monkeypatch.setenv("HUB_HEALTH", "off")
    assert not hub_agent.record_health("login", False, None, "x")
    assert _events(health_home) == []


def test_health_classify():
    c = hub_agent.classify
    assert c("Command blocked for security: iex (alias for Invoke-Expression)") == "CMD_BLOCKED"
    assert c("登录未完成：超时或状态不匹配") == "LOGIN_TIMEOUT"
    assert c("Error: listen EADDRINUSE: address already in use 127.0.0.1:17890") == "PORT_IN_USE"
    assert c("这个应用需要 Node.js 20 或更高版本（本机没有检测到 Node.js）") == "NODE_MISSING"
    assert c("校验失败：应用包的 SHA-256 与中枢发布的不一致") == "APP_DOWNLOAD_FAILED"
    assert c("奇怪的错误") == "UNKNOWN" and c("奇怪的错误", "APP_LAUNCH_FAILED") == "APP_LAUNCH_FAILED"


class _Resp:
    def __init__(self, code):
        self.status_code = code


def test_health_flush_keeps_offset_on_failure_and_reads_all_files(health_home):
    hub_agent.record_health("launch", True, now=1.0)
    hub_agent.record_health("launch", False, "PORT_IN_USE", "端口被占用", now=2.0)
    other = health_home / "HubApps" / "logs" / "health-xhs-workbench.jsonl"  # 应用自己写的文件
    other.write_text(json.dumps({"stage": "runtime", "ok": False, "code": "ACCESS_LOCKED"}) + "\n" + '{"half": ', encoding="utf-8")
    sent = []
    assert hub_agent.flush_health({}, "http://hub", post=lambda stem, items: (_ for _ in ()).throw(OSError("down"))) == 0  # 断网：不推进
    assert hub_agent.flush_health({}, "http://hub", post=lambda stem, items: sent.append(items) or _Resp(200)) == 3
    assert sum(len(b) for b in sent) == 3  # 半行没写完的不发
    assert hub_agent.flush_health({}, "http://hub", post=lambda stem, items: sent.append(items) or _Resp(200)) == 0  # 不重复发


def test_report_app_event_records_launch_and_missing(health_home, monkeypatch):
    monkeypatch.setattr(hub_agent.httpx, "post", lambda *a, **k: _Resp(200))
    ticket = {"app_id": "xhs-workbench", "version": "0.7.9"}
    hub_agent.report_app_event({"access_token": "t"}, "http://hub", ticket, {"ok": True, "url": "http://127.0.0.1:17890", "missing": ["CodeBuddy CLI", "系统浏览器"]})
    hub_agent.report_app_event({"access_token": "t"}, "http://hub", ticket, {"ok": False, "reason": "启动超时（60 秒）"})
    evs = _events(health_home)
    assert [(e["stage"], e["code"]) for e in evs] == [("launch", "OK"), ("doctor", "CLI_MISSING"), ("doctor", "BROWSER_MISSING"), ("launch", "APP_LAUNCH_FAILED")]


def test_stale_copies_found_in_agent_skill_dirs(tmp_path, monkeypatch):
    wb = tmp_path / ".workbuddy" / "skills"
    monkeypatch.setattr(hub_agent, "WORKBUDDY_SKILLS", wb)
    monkeypatch.setattr(hub_agent, "CODEBUDDY_HOME", tmp_path / ".codebuddy")
    (wb / "xhs-workbench").mkdir(parents=True)
    (wb / "xhs-workbench" / "SKILL.md").write_text("x", encoding="utf-8")         # 早期整包发的副本
    (wb / "hub-xhs-writing").mkdir()
    (wb / "hub-xhs-writing" / "SKILL.md").write_text("x", encoding="utf-8")      # 中枢同步的技能：不算
    (tmp_path / ".claude" / "skills" / "xhs-workbench").mkdir(parents=True)        # 没有 SKILL.md：不算
    found = hub_agent.stale_copies([{"id": "xhs-workbench", "name": "小红书运营工作台"}, {"id": "../x"}], home=tmp_path)
    assert [(a["id"], d) for a, d in found] == [("xhs-workbench", wb / "xhs-workbench")]
    (wb / "xhs-workbench" / hub_agent.WB_MARKER).write_text("")                   # 带中枢标记的不算
    assert hub_agent.stale_copies([{"id": "xhs-workbench"}], home=tmp_path) == []


def test_connector_pins_python_below_314():
    head = (Path(hub_agent.__file__).read_text(encoding="utf-8")).split("# ///")[1]
    assert 'requires-python = ">=3.11,<3.14"' in head  # uv 曾在新电脑上选了 3.15，pyyaml 没有预编译包，接入直接失败


def test_bridge_skips_resync_within_10_minutes(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_agent, "HOME", tmp_path)
    assert not hub_agent.synced_recently()                       # 没同步过
    (tmp_path / "profile.json").write_text("{}", encoding="utf-8")
    assert hub_agent.synced_recently()
    import os as _os
    old = (tmp_path / "profile.json").stat().st_mtime - 601
    _os.utime(tmp_path / "profile.json", (old, old))
    assert not hub_agent.synced_recently()


def test_setup_does_not_relogin_on_temporary_hub_error(tmp_path, monkeypatch):
    """中枢临时出错（如模型网关限流导致 502）时，接入不应当成登录过期去弹浏览器。"""
    monkeypatch.setattr(hub_agent, "HOME", tmp_path)
    monkeypatch.setattr(hub_agent, "CREDS", tmp_path / "credentials.json")
    (tmp_path / "credentials.json").write_text(json.dumps({"hub": "http://hub", "refresh_token": "r"}), encoding="utf-8")
    monkeypatch.setattr(hub_agent, "agent_clients", lambda: [])
    logins = []
    monkeypatch.setattr(hub_agent, "cmd_login", lambda a: logins.append(a))

    def sync_fail(msg):
        def f(*a, **k):
            hub_agent.fail(msg)
        return f
    monkeypatch.setattr(hub_agent, "cmd_sync", sync_fail("领取配置失败：New API /api/token/26/key 返回 HTTP 429（非 JSON 响应，可能被限流）"))
    with pytest.raises(SystemExit):
        hub_agent.cmd_setup(hub_agent.argparse.Namespace(hub="http://hub"))
    assert logins == []
    monkeypatch.setattr(hub_agent, "cmd_sync", sync_fail("登录已过期，请重新运行 login"))
    monkeypatch.setattr(hub_agent, "configure_agents", lambda *a: [])
    monkeypatch.setattr(hub_agent, "register_app_root", lambda: [])
    monkeypatch.setattr(hub_agent, "_write_hub_mcp_config", lambda: tmp_path / "hub-mcp.json")
    hub_agent.cmd_setup(hub_agent.argparse.Namespace(hub="http://hub"))
    assert len(logins) == 1


def test_token_prints_only_hub_token_and_expiry(monkeypatch, capsys):
    """token 命令给本机公司应用取令牌：只输出中枢地址、访问令牌和过期时间，不带刷新令牌"""
    creds = {"hub": "http://hub:8088", "access_token": "a", "refresh_token": "r", "expires_at": 123}
    monkeypatch.setattr(hub_agent, "fresh_creds", lambda: creds)
    hub_agent.cmd_token()
    out = json.loads(capsys.readouterr().out)
    assert out == {"hub": "http://hub:8088", "access_token": "a", "expires_at": 123}
