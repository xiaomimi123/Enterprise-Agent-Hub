"""接入器（agent/hub_agent.py）的灰度发布与回滚。

背景：接入器挂载在中枢上，员工电脑发现比本机新就自动替换自己，所以改一次文件等于发给所有人；而且版本号只增不减，
发错了没法让电脑退回去。这里加一层「谁拿到哪个版本」：

- 没有 `agent/rollout.json` 时和以前完全一样（所有人拿挂载的那份）。
- 有 rollout.json 时：`stable` 是大家默认拿的版本；`candidate` 只给 `canary_users` 里的人；`force_stable: true` 表示
  「所有人退回 stable，哪怕比本机版本低」（回滚）。
- 每个版本的文件放在 `agent/releases/<版本>/hub_agent.py`（`tools/release-agent.py snapshot` 生成，不进 git）；没有快照但挂载的
  文件就是这个版本时，也能用挂载的那份。
- 老版本接入器（0.5.8–0.5.11）只会问 `/api/agent/config` 和下载 `/api/agent/hub_agent.py`，这两个在有 rollout.json 时只给 stable，
  所以老电脑永远拿不到灰度版本。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("hub.rollout")
_VER = re.compile(r"^\d+(\.\d+){1,3}$")
_VERSION_LINE = re.compile(r'^VERSION = "([^"]+)"', re.M)


def file_version(f: Path) -> str:
    try:
        m = _VERSION_LINE.search(f.read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def load(agent_dir: str | Path) -> dict | None:
    """读 rollout.json；不存在或写坏了都返回 None（退回「所有人拿挂载的那份」，并留一条日志），不能因为配置错让接入器下不了。"""
    f = Path(agent_dir) / "rollout.json"
    if not f.is_file():
        return None
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
        stable = str(raw.get("stable") or "").strip()
        cand = str(raw.get("candidate") or "").strip()
        if not _VER.match(stable) or (cand and not _VER.match(cand)):
            raise ValueError("stable / candidate 必须是 x.y.z 形式的版本号")
        users = raw.get("canary_users") or []
        if not isinstance(users, list):
            raise ValueError("canary_users 必须是列表")
        return {"stable": stable, "candidate": cand, "canary_users": {str(u) for u in users},
                "force_stable": bool(raw.get("force_stable"))}
    except (OSError, ValueError, AttributeError) as e:
        log.warning("rollout.json 无效，按没有灰度配置处理：%s", e)
        return None


def stable_version(agent_dir: str | Path) -> str:
    r = load(agent_dir)
    return r["stable"] if r else file_version(Path(agent_dir) / "hub_agent.py")


def choose(agent_dir: str | Path, user: str | None) -> dict:
    """这个人该用哪个版本：{version, force}。force 表示允许比本机低（回滚）。"""
    r = load(agent_dir)
    if not r:
        return {"version": file_version(Path(agent_dir) / "hub_agent.py"), "force": False}
    if r["candidate"] and user and user in r["canary_users"]:
        return {"version": r["candidate"], "force": False}
    return {"version": r["stable"], "force": r["force_stable"]}


def script_for(agent_dir: str | Path, version: str | None = None) -> Path | None:
    """某个版本的接入器文件。没指定版本就是 stable。只允许 rollout 里列出的版本（stable / candidate），防止任意路径。"""
    d = Path(agent_dir)
    mounted = d / "hub_agent.py"
    r = load(d)
    if not r:
        return mounted if mounted.is_file() and (not version or file_version(mounted) == version) else None
    version = version or r["stable"]
    if version not in (r["stable"], r["candidate"]) or not _VER.match(version):
        return None
    snap = d / "releases" / version / "hub_agent.py"
    if snap.is_file():
        return snap
    return mounted if file_version(mounted) == version else None
