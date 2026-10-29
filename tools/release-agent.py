#!/usr/bin/env python3
"""接入器（agent/hub_agent.py）的发布工具：快照、灰度、回滚。原理见 console/backend/app/rollout.py。

  python tools/release-agent.py status                         看现在谁拿哪个版本
  python tools/release-agent.py snapshot [--file 路径]          把当前（或指定的）hub_agent.py 存成 agent/releases/<版本>/hub_agent.py
  python tools/release-agent.py set --stable 0.5.11 [--candidate 0.5.12] [--canary 用户名 ...] [--force-stable]
  python tools/release-agent.py clear                          删掉 rollout.json，回到「所有人拿挂载的那份」

发布流程：改代码并升 VERSION → snapshot → set（stable 保持旧版，candidate 填新版，canary 填几个人）→ 在「应用健康」里观察 →
set --stable 新版（放量）→ 出问题：set --stable 旧版 --force-stable（回滚，电脑下次问更新时退回，最长 6 小时）。
放量 / 回滚前先确认两个版本的快照都在 releases/ 里（status 会检查）。部署机上的 agent/ 是只读挂载进容器的，在宿主机上改文件即可，不用重启。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent / "agent"
ROLLOUT = AGENT / "rollout.json"
VER = re.compile(r"^\d+(\.\d+){1,3}$")


def file_version(f: Path) -> str:
    m = re.search(r'^VERSION = "([^"]+)"', f.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def load() -> dict:
    return json.loads(ROLLOUT.read_text(encoding="utf-8-sig")) if ROLLOUT.is_file() else {}


def cmd_status(_a) -> int:
    mounted = file_version(AGENT / "hub_agent.py")
    cfg = load()
    print(f"挂载的 hub_agent.py：{mounted}")
    snaps = sorted(p.parent.name for p in (AGENT / "releases").glob("*/hub_agent.py")) if (AGENT / "releases").is_dir() else []
    print(f"已有快照：{', '.join(snaps) or '无'}")
    if not cfg:
        print("没有 rollout.json：所有人拿挂载的那份。")
        return 0
    print(f"stable={cfg.get('stable')}  candidate={cfg.get('candidate') or '-'}  灰度名单={cfg.get('canary_users') or []}  force_stable={bool(cfg.get('force_stable'))}")
    bad = 0
    for role in ("stable", "candidate"):
        v = cfg.get(role)
        if v and v not in snaps and v != mounted:
            print(f"!! {role} {v} 既没有快照也不是挂载的版本，下载会 404")
            bad = 1
    return bad


def cmd_snapshot(a) -> int:
    src = Path(a.file) if a.file else AGENT / "hub_agent.py"
    v = file_version(src)
    if not VER.match(v):
        print(f"{src} 里读不到合法的 VERSION", file=sys.stderr)
        return 1
    dst = AGENT / "releases" / v / "hub_agent.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        print(f"{v} 的快照已存在且内容不同。同一个版本号不能发两份不同的文件，请先升 VERSION。", file=sys.stderr)
        return 1
    shutil.copy2(src, dst)
    print(f"已保存 {dst}")
    return 0


def cmd_set(a) -> int:
    cfg = {"stable": a.stable, "candidate": a.candidate or "", "canary_users": a.canary or [], "force_stable": bool(a.force_stable)}
    for v in (cfg["stable"], cfg["candidate"]):
        if v and not VER.match(v):
            print(f"版本号不合法：{v}", file=sys.stderr)
            return 1
    ROLLOUT.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cmd_status(a)


def cmd_clear(_a) -> int:
    ROLLOUT.unlink(missing_ok=True)
    print("已删除 rollout.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("snapshot")
    p.add_argument("--file")
    p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser("set")
    p.add_argument("--stable", required=True)
    p.add_argument("--candidate")
    p.add_argument("--canary", nargs="*")
    p.add_argument("--force-stable", action="store_true")
    p.set_defaults(fn=cmd_set)
    sub.add_parser("clear").set_defaults(fn=cmd_clear)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
