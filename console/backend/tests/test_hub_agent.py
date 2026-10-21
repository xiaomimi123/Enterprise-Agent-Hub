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
    assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["model"] == "deepseek-v4"
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
    s.write_text(json.dumps({"model": "my-own-choice", "env": {"A": "1"}}), encoding="utf-8")                 # 员工自己改了默认模型
    hub_agent.sync_codebuddy_models(c2, home, state)
    assert json.loads(s.read_text(encoding="utf-8")) == {"model": "my-own-choice", "env": {"A": "1"}}


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
