"""应用健康：员工电脑上安装、登录、打开应用、自检和运行时的结果自动回传中枢，管理员在「应用健康」页按版本 / 系统 / agent 看失败率和常见报错。

数据流：接入器（以及安装脚本、工作台）把事件追加写到本机 ~/HubApps/logs/health*.jsonl → 接入器批量转发到 POST /api/agent/health
（员工令牌，单批 ≤ 50 条）→ 这里清洗、再去一次隐私 → app_health_events 表，只保留 RETENTION_DAYS 天。
成功也上报，才算得出成功率。不上报提示词、对话、正文、账号名、Cookie、令牌、密码、带参数的网址。
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

RETENTION_DAYS = 7
MAX_BATCH = 50
MAX_MESSAGE = 300
RATE_LIMIT = 1000  # 每人每小时最多收这么多条，防止某台电脑的死循环刷爆表
STAGES = {"install": "安装", "login": "登录", "launch": "打开应用", "doctor": "自检", "task": "运行任务", "runtime": "运行", "preflight": "安装前自检"}

# 错误码目录：本机和控制台显示同一句处理办法。没有对应码的归为 UNKNOWN，方便决定下一个要补哪个码
CODES: dict[str, tuple[str, str]] = {
    "OK": ("成功", ""),
    "NET_UNREACHABLE": ("连不上中枢", "确认电脑和中枢在同一网络（或能路由过去）：浏览器打开中枢地址能出登录页再继续。"),
    "LOGIN_TIMEOUT": ("登录超时", "登录页可能开在后台标签里；重新运行命令，只保留一个登录页，在 10 分钟内完成登录。"),
    "LOGIN_FAILED": ("登录失败", "看报错原文：状态校验失败就关掉旧登录页重来；账号停用或锁定请联系管理员。"),
    "CMD_BLOCKED": ("命令被 agent 拦截", "agent 的安全策略拦了这条命令（如 iex、Start-Process）。改用先下载再 -File 执行，或让员工 Win+R 自己运行。"),
    "FILE_BLOCKED": ("写文件被 agent 拦截", "把 HubApps 目录登记为 agent 允许写入的目录（重新运行接入命令会自动登记）。"),
    "PROC_KILLED": ("进程被结束", "应用由 agent 拉起，agent 退出时被一起结束。用桌面快捷方式启动应用。"),
    "NODE_MISSING": ("缺少 Node.js", "重新运行接入命令，询问时选择安装；没有管理员权限也可以（用便携版）。"),
    "NPM_FAILED": ("npm 安装失败", "看报错原文；执行策略问题改用 npm.cmd，网络问题检查代理。"),
    "CLI_MISSING": ("缺少 CodeBuddy CLI", "重新运行接入命令，询问时选择安装 CodeBuddy CLI。"),
    "CLI_NOT_LOGGED_IN": ("CodeBuddy 未登录", "终端运行 codebuddy，输入 /login，用自己的 CodeBuddy 账号登录一次。"),
    "BROWSER_MISSING": ("没有系统浏览器", "安装 Microsoft Edge 或 Google Chrome。"),
    "PORT_IN_USE": ("端口被占用", "关掉占用端口的程序，或重启电脑后再打开应用。"),
    "APP_DOWNLOAD_FAILED": ("应用下载失败", "检查到中枢的网络；校验失败说明包被改过，请管理员重新上传。"),
    "APP_LAUNCH_FAILED": ("应用启动失败", "看报错原文；仍不行把应用自己的日志发给管理员。"),
    "ACCESS_LOCKED": ("自动访问已锁定", "账号的自动访问锁在生效；确认平台没有限制后，在工作台网页里人工解除。"),
    "STALE_COPY": ("本机有应用的旧副本", "agent 的技能目录里有早期整包发的应用副本，agent 会直接运行它而绕开中枢。删掉那个文件夹（数据不在里面），以后双击桌面快捷方式或对 agent 说「打开某应用」。"),
    # 安装前自检（agent/preflight.ps1）。FAIL 表示照现状装不上，WARN 表示能装但某项功能会受影响
    "PREFLIGHT_OS_UNSUPPORTED": ("系统版本不支持", "需要 64 位 Windows 10 1809（17763）或更新版本。"),
    "PREFLIGHT_PS_CONSTRAINED": ("PowerShell 被限制", "安全软件把 PowerShell 限制成受限语言模式，脚本跑不起来。请 IT 放行，或换一台电脑安装。"),
    "PREFLIGHT_EXEC_POLICY": ("PowerShell 执行策略过严", "磁盘上的 .ps1 脚本不能直接运行。用 powershell -ExecutionPolicy Bypass -File <脚本> 运行。"),
    "PREFLIGHT_AGENT_SANDBOX": ("在 agent 里启动", "这条命令是被 agent（WorkBuddy 等）拉起的：沙箱可能拦截步骤、agent 退出时会结束它启动的程序。请关掉 agent，自己按 Win+R 粘贴命令运行。"),
    "PREFLIGHT_PATH_UNSAFE": ("安装目录路径不稳妥", "路径含中文、空格或过长，批处理启动器容易出错。把 HUB_APPS_ROOT 设成纯英文目录（如 C:/HubApps）后重新运行。"),
    "PREFLIGHT_DISK_LOW": ("磁盘空间不足", "安装盘剩余空间不足 1.5 GB。清理空间，或把 HUB_APPS_ROOT 设到别的盘。"),
    "PREFLIGHT_NOT_WRITABLE": ("安装目录不可写", "受控文件夹访问或权限规则拦住了写入。放行该目录，或把 HUB_APPS_ROOT 设到别处。"),
    "PREFLIGHT_HUB_UNREACHABLE": ("连不上中枢", "浏览器打开中枢地址，打不开就检查网络 / VPN；这台电脑必须能访问中枢。"),
    "PREFLIGHT_HUB_SLOW": ("到中枢的网络很慢", "响应超过 2 秒，下载可能超时。换到更稳的网络再试。"),
    "PREFLIGHT_CLOCK_SKEW": ("电脑时间不准", "与中枢相差超过 5 分钟，登录令牌可能被拒绝。把日期、时间、时区设为自动。"),
    "PREFLIGHT_CASDOOR_UNREACHABLE": ("连不上登录服务", "登录服务的端口被网络拦住了（中枢能通但登录端口不通）。请 IT 放行该端口，或换到和中枢同一网络。"),
    "PREFLIGHT_MCP_UNREACHABLE": ("连不上中枢 MCP", "MCP 端口被网络拦住了。请 IT 放行该端口，或换到和中枢同一网络。"),
    "PREFLIGHT_PROXY_DEAD": ("系统代理指向未运行的程序", "设置了本机代理但那个程序没在运行。关掉系统代理，或先启动那个代理程序。"),
    "PREFLIGHT_PORT_CALLBACK": ("登录回调端口被占用", "关闭占用该端口的程序（或重启电脑）后重试，登录需要这个端口。"),
    "PREFLIGHT_NO_EDGE": ("没有 Edge 浏览器", "页面采集需要装了 WorkBuddy 扩展的 Edge；其他功能不受影响。"),
    "PREFLIGHT_AV_BLOCK": ("杀毒软件拦截过我们的文件", "最近 7 天 Defender 拦截或标记过安装目录里的文件。把安装目录加入杀毒软件排除项后重试。"),
    "BUNDLE_FAILED": ("底座包安装失败", "从中枢下载或校验底座包（Node / uv / Python）失败，会退回联网安装。校验失败说明文件被改过或下载不完整，请管理员重新构建底座包（tools/build-bundle）；下载失败检查到中枢的网络。"),
    "BASE_OUTDATED": ("底座版本过旧", "本机的底座运行环境低于这个应用要求的版本。重新运行安装命令即可升级（会从中枢下载新的底座包，旧的保留为 .prev 以便回退）。"),
    "UNKNOWN": ("未分类", "看报错原文；常见的话请让开发补一个错误码。"),
}

_FIELDS = {"device_id": 64, "app_id": 64, "app_version": 32, "os": 40, "os_version": 40, "arch": 16,
           "agent": 40, "agent_version": 32, "connector_version": 16}

# 去隐私：用户目录换成 ~，邮箱 / 手机号 / 令牌打码，网址去掉参数
_RX = [
    (re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"']+"), "~"),
    (re.compile(r"/(?:Users|home)/[^/\s\"']+"), "~"),
    (re.compile(r"(?i)\b(bearer|token|password|passwd|pwd|secret|api[_-]?key|access_token|refresh_token)\b(\s*[:=]\s*|\s+)\S+"), r"\1\2***"),
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]*"), "***"),  # JWT
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "sk-***"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "***@***"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "1**********"),
    (re.compile(r"(https?://[^\s?#\"']+)[?#][^\s\"']*"), r"\1"),
]


def redact(text: str) -> str:
    text = str(text or "")
    for rx, rep in _RX:
        text = rx.sub(rep, text)
    return text.strip()[:MAX_MESSAGE]


def _ts(value, now: datetime) -> datetime | None:
    """事件时间：本机记的时间，限定在 [now - 保留天数, now + 5 分钟]；更早的已过保留期，丢弃。"""
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except ValueError:
        return now
    if t < now - timedelta(days=RETENTION_DAYS):
        return None
    return min(t, now + timedelta(minutes=5))


def clean(ev: dict, now: datetime | None = None) -> dict | None:
    """白名单字段 + 截断 + 去隐私；格式不对的返回 None（整批里跳过这一条，不影响其他）。"""
    if not isinstance(ev, dict):
        return None
    now = now or datetime.now(timezone.utc)
    stage = str(ev.get("stage") or "")
    if stage not in STAGES:
        return None
    ok = bool(ev.get("ok"))
    code = str(ev.get("code") or ("OK" if ok else "UNKNOWN")).upper()
    if code not in CODES:
        code = "UNKNOWN"
    at = _ts(ev.get("at"), now)
    if at is None:
        return None
    out = {k: str(ev.get(k) or "").strip()[:n] for k, n in _FIELDS.items()}
    out.update(stage=stage, ok=ok, code="OK" if ok else code, message="" if ok else redact(ev.get("message") or ""), at=at)
    return out


_rate: dict[tuple[str, str], list[float]] = defaultdict(list)


def allow(org: str, user: str, n: int, now: float | None = None) -> bool:
    """每人每小时最多 RATE_LIMIT 条（进程内计数，多副本时各算各的，够用）。"""
    now = now or time.time()
    hits = [t for t in _rate[(org, user)] if t > now - 3600]
    if len(hits) + n > RATE_LIMIT:
        _rate[(org, user)] = hits
        return False
    _rate[(org, user)] = hits + [now] * n
    return True


def _rate_of(rows: list[dict], stage: str) -> dict:
    xs = [r for r in rows if r["stage"] == stage]
    ok = sum(1 for r in xs if r["ok"])
    return {"total": len(xs), "ok": ok, "rate": round(ok / len(xs), 3) if xs else None}


def summarize(rows: list[dict], names: dict[str, str] | None = None) -> dict:
    """把事件行汇总成「应用健康」页的数据：顶部数字、常见报错、设备列表。rows 按时间倒序。"""
    names = names or {}
    fails = [r for r in rows if not r["ok"]]
    codes = []
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in fails:
        by_code[r["code"]].append(r)
    for code, xs in sorted(by_code.items(), key=lambda kv: -len(kv[1])):
        label, fix = CODES.get(code, CODES["UNKNOWN"])
        codes.append({
            "code": code, "label": label, "fix": fix, "count": len(xs),
            "people": len({r["user_name"] for r in xs}), "devices": len({(r["user_name"], r["device_id"]) for r in xs}),
            "stages": dict(Counter(STAGES.get(r["stage"], r["stage"]) for r in xs)),
            "os": dict(Counter(r["os"] or "未知" for r in xs)), "agents": dict(Counter(r["agent"] or "未知" for r in xs)),
            "versions": dict(Counter(f"{r['app_id']} {r['app_version']}".strip() or "接入器" for r in xs)),
            "last_at": xs[0]["at"], "sample": next((r["message"] for r in xs if r["message"]), ""),
        })
    devices: dict[tuple[str, str], dict] = {}
    for r in rows:  # 倒序：每台设备第一条就是最新的
        key = (r["user_name"], r["device_id"])
        d = devices.get(key)
        if d is None:
            d = devices[key] = {"user_name": r["user_name"], "display_name": names.get(r["user_name"]) or r.get("display_name") or r["user_name"],
                                "device_id": r["device_id"], "os": r["os"], "os_version": r["os_version"], "arch": r["arch"],
                                "agent": r["agent"], "agent_version": r["agent_version"], "connector_version": r["connector_version"],
                                "app_version": "", "last_at": r["at"], "last_ok_at": None, "last_fail_at": None, "last_code": "", "fails": 0}
        for k in ("os", "os_version", "arch", "agent", "agent_version", "connector_version"):  # 最新一条没带的（比如应用自己写的事件），用较早的补上
            if not d[k] and r[k]:
                d[k] = r[k]
        if r["app_version"] and not d["app_version"]:
            d["app_version"] = f"{r['app_id']} {r['app_version']}"
        if r["ok"] and d["last_ok_at"] is None:
            d["last_ok_at"] = r["at"]
        if not r["ok"]:
            d["fails"] += 1
            if d["last_fail_at"] is None:
                d["last_fail_at"], d["last_code"] = r["at"], r["code"]
    for d in devices.values():  # 最近一次是失败（之后没再成功过）的设备排前面
        d["failing"] = bool(d["last_fail_at"] and (d["last_ok_at"] is None or d["last_fail_at"] > d["last_ok_at"]))
    return {
        "totals": {"events": len(rows), "fails": len(fails), "people": len({r["user_name"] for r in rows}),
                   "devices": len(devices), "fail_people": len({r["user_name"] for r in fails}),
                   "install": _rate_of(rows, "install"), "login": _rate_of(rows, "login"), "launch": _rate_of(rows, "launch")},
        "codes": codes,
        "devices": sorted(devices.values(), key=lambda d: (not d["failing"], -d["last_at"].timestamp())),
        "catalog": {k: {"label": v[0], "fix": v[1]} for k, v in CODES.items()},
    }


def demo_rows(now: datetime | None = None) -> list[dict]:
    """演示模式（没有数据库）用的示例事件，按时间倒序。"""
    now = now or datetime.now(timezone.utc)
    base = {"display_name": "", "os_version": "", "arch": "x64", "agent_version": "", "message": ""}
    spec = [  # (分钟前, 人, 显示名, 设备, 阶段, 成功, 码, 系统, agent, 应用版本, 原文)
        (5, "lisi", "李四", "a1b2c3", "launch", False, "PORT_IN_USE", "Windows 10", "WorkBuddy", "0.7.9", "Error: listen EADDRINUSE 127.0.0.1:17890"),
        (12, "wangwu", "王五", "d4e5f6", "login", False, "NET_UNREACHABLE", "Windows 10", "WorkBuddy", "", "连不上中枢 http://192.168.0.41:8088：ConnectTimeout"),
        (30, "zhangsan", "张三", "0a9b8c", "launch", True, "OK", "macOS", "CodeBuddy CLI", "0.7.9", ""),
        (45, "lisi", "李四", "a1b2c3", "doctor", False, "CLI_MISSING", "Windows 10", "WorkBuddy", "0.7.9", "缺少能力：CodeBuddy CLI"),
        (60, "zhaoliu", "赵六", "7f7e7d", "install", False, "CMD_BLOCKED", "Windows 11", "WorkBuddy", "", "Command blocked for security: iex (alias for Invoke-Expression) executes arbitrary code"),
        (90, "zhangsan", "张三", "0a9b8c", "install", True, "OK", "macOS", "CodeBuddy CLI", "", ""),
        (120, "lisi", "李四", "a1b2c3", "install", True, "OK", "Windows 10", "WorkBuddy", "", ""),
        (180, "wangwu", "王五", "d4e5f6", "login", False, "NET_UNREACHABLE", "Windows 10", "WorkBuddy", "", "连不上中枢 http://192.168.0.41:8088：ConnectTimeout"),
    ]
    return [{**base, "user_name": u, "display_name": n, "device_id": d, "stage": st, "ok": ok, "code": c, "os": os_, "agent": ag,
             "connector_version": "0.5.0", "app_id": "xhs-workbench" if v else "", "app_version": v, "message": m,
             "at": now - timedelta(minutes=mins)} for mins, u, n, d, st, ok, c, os_, ag, v, m in spec]


# ---------------- 在线状态与接入器版本（来自接入器每分钟的心跳，每人一条） ----------------

from .presence import is_online  # noqa: E402  在线的唯一判断在 presence.py


def version_tuple(v: str | None) -> tuple:
    try:
        return tuple(int(x) for x in str(v or "").strip().split("."))
    except ValueError:
        return ()


def is_outdated(v: str | None, latest: str | None) -> bool:
    """接入器版本低于中枢正在发布的版本。版本未知（没有心跳）的不算旧版，单独标「未知」。"""
    a, b = version_tuple(v), version_tuple(latest)
    return bool(a) and bool(b) and a < b


def merge_presence(summary: dict, presence: dict[str, dict], latest: str | None, names: dict[str, str] | None = None,
                   days: int = RETENTION_DAYS, now: datetime | None = None) -> dict:
    """把心跳合并进设备列表：每台设备补上「最近在线」、心跳里的 agent 和接入器版本、是否旧版；
    这段时间有心跳却没有任何健康事件的人（旧版接入器不回传事件）也列出来，标成「没有回传」。"""
    now = now or datetime.now(timezone.utc)
    names = names or {}

    def info(p: dict | None, fallback_version: str = "") -> dict:
        seen = p.get("last_seen") if p else None
        # 心跳和健康事件里各有一个接入器版本，取较新的（升级后桥还没重新连上时，心跳里还是旧版本）
        version = max([v for v in ((p.get("version") if p else None), fallback_version) if v], key=version_tuple, default="")
        return {"last_seen": seen, "online": is_online(seen, now),
                "presence_agent": (p.get("client") if p else "") or "", "current_version": version or "",
                "outdated": is_outdated(version, latest), "version_unknown": not version}

    devices = summary["devices"]
    for d in devices:
        d.update(info(presence.get(d["user_name"]), d.get("connector_version", "")), no_events=False)
    have = {d["user_name"] for d in devices}
    for user, p in presence.items():
        seen = p.get("last_seen")
        if user in have or not seen or (now - seen) > timedelta(days=days) or (names and user not in names):
            continue  # 已删除的账号（不在成员名单里）、这段时间没出现过的不列
        devices.append({"user_name": user, "display_name": names.get(user) or user, "device_id": "", "os": p.get("os") or "",
                        "os_version": "", "arch": "", "agent": p.get("client") or "", "agent_version": "",
                        "connector_version": p.get("version") or "", "app_version": "", "last_at": seen, "last_ok_at": None,
                        "last_fail_at": None, "last_code": "", "fails": 0, "failing": False, "no_events": True, **info(p)})
    devices.sort(key=lambda d: (not d["failing"], not d["outdated"], -(d["last_seen"] or d["last_at"]).timestamp()))
    people = {d["user_name"]: d for d in devices}
    summary["totals"].update(online=sum(1 for d in people.values() if d["online"]),
                             outdated=sum(1 for d in people.values() if d["outdated"]),
                             version_unknown=sum(1 for d in people.values() if d["version_unknown"]))
    summary["latest_connector"] = latest or ""
    return summary


def demo_presence(now: datetime | None = None) -> dict[str, dict]:
    now = now or datetime.now(timezone.utc)
    return {"lisi": {"client": "WorkBuddy", "version": "0.5.0", "os": "Windows 10", "last_seen": now - timedelta(seconds=40)},
            "zhangsan": {"client": "CodeBuddy CLI", "version": "0.5.0", "os": "macOS", "last_seen": now - timedelta(hours=3)},
            "wangwu": {"client": "WorkBuddy", "version": "0.4.0", "os": "Windows 10", "last_seen": now - timedelta(hours=20)},
            "sunqi": {"client": "CodeBuddy CLI", "version": "0.4.0", "os": "Windows 10", "last_seen": now - timedelta(minutes=1)},
            "zhouba": {"client": None, "version": None, "os": None, "last_seen": now - timedelta(days=2)}}


def preflight_events(body: dict, now: datetime | None = None) -> tuple[str, list[dict]]:
    """安装前自检的匿名上报：只收 FAIL / WARN 的错误码；返回 (设备号, 已清洗的事件)。设备号只取字母数字，限长。"""
    now = now or datetime.now(timezone.utc)
    dev = re.sub(r"[^0-9a-zA-Z]", "", str(body.get("device_id") or ""))[:32]
    base = {k: str(body.get(k) or "").strip()[:n] for k, n in _FIELDS.items()}
    base["device_id"] = dev
    events = []
    for r in (body.get("results") or [])[:50]:
        if not isinstance(r, dict):
            continue
        code = str(r.get("code") or "").upper()
        if not code.startswith("PREFLIGHT_") or code not in CODES:
            continue
        events.append({**base, "stage": "preflight", "ok": False, "code": code, "message": redact(r.get("message") or ""), "at": now})
    return dev, events
