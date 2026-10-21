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
