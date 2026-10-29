"""应用注册表：管理员在 apps/<应用 id>/ 下放 app.json 和 <版本>.zip，员工通过 open_app 取得启动凭证。

- 注册表只信目录里的文件：id 必须和目录名一致，查询时按注册表找，绝不把外部输入拼进路径
- zip 的 SHA-256 在请求时按 (修改时间, 大小) 缓存计算：管理员替换文件即生效，无需重启中枢
- 下载走带签名、短有效期的链接（HMAC-SHA256，与生成结果下载同一套思路），校验失败一律 404
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from .config import settings

log = logging.getLogger("hub.apps")
APP_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# app.json 的 requires：应用声明的运行条件。node 是版本要求；agent_cli 是应用背后的命令行 agent（接入器会检查它是否装好、是否走中枢模型）；
# base_min 是应用要求的最低底座运行环境版本（员工机 runtime/BASE_VERSION，低了只提示升级、不拦打开）；capabilities 是应用需要的能力（browser = 需要 agent 能控制浏览器：agent_cli + Playwright + 系统浏览器）；playwright_mcp 可选，指定版本。
ALLOWED_AGENT_CLIS = {"codebuddy"}
ALLOWED_CAPABILITIES = {"browser"}


def _check_requires(r: dict) -> str | None:
    """requires 不合法返回原因（应用会被跳过并写日志），合法返回 None。未知的键原样保留，方便以后扩展。"""
    if "node" in r and not isinstance(r["node"], str):
        return "node 必须是字符串，如 \">=18\""
    if "agent_cli" in r and r["agent_cli"] not in ALLOWED_AGENT_CLIS:
        return f"agent_cli 只支持 {sorted(ALLOWED_AGENT_CLIS)}"
    caps = r.get("capabilities", [])
    if not isinstance(caps, list) or any(c not in ALLOWED_CAPABILITIES for c in caps):
        return f"capabilities 只支持 {sorted(ALLOWED_CAPABILITIES)}"
    if "browser" in caps and "agent_cli" not in r:
        return "声明了 browser 能力就必须同时声明 agent_cli（浏览器自动化靠命令行 agent 完成）"
    if "base_min" in r and not (isinstance(r["base_min"], str) and re.fullmatch(r"\d+\.\d+\.\d+", r["base_min"])):
        return "base_min 必须是形如 1.0.0 的底座版本号"
    if "playwright_mcp" in r and not (isinstance(r["playwright_mcp"], str) and re.fullmatch(r"\d+\.\d+\.\d+", r["playwright_mcp"])):
        return "playwright_mcp 必须是形如 0.0.83 的版本号"
    return None
LINK_TTL = 600  # 下载链接有效期（秒）


# ---- 接入说明（apps/<id>/guide.json，可选）----
# 控制台「应用」页按应用展示：给谁用、怎么打开、员工首次要做什么、管理员要知道什么、限制、常见问题。
# 和 app.json 分开：改说明不用动版本号，也不用重新打包；guide.json 入库（见 .gitignore），说明的修改走代码评审。
# 写错的 guide 只是不显示（应用照常能打开）：说明写坏了不能连累员工打开应用。
_GUIDE_TEXT = {"summary": 200, "open": 400}
_GUIDE_LISTS = {"audience": (10, 30), "admin_notes": (12, 500), "limits": (12, 400)}   # 键 -> (最多几条, 每条最多几字)
_GUIDE_PAIRS = {"employee_steps": ("title", "body", 12, 40, 800), "faq": ("q", "a", 20, 160, 800), "docs": ("title", "path", 8, 60, 200)}


def _has_control_chars(v) -> bool:
    """文本里夹了控制字符（多半是 JSON 里的反斜杠转义写错了，如路径里的 auth 前面的反斜杠变成了响铃字符）：换行和制表除外"""
    if isinstance(v, str):
        return any(ord(c) < 32 and c not in (chr(10), chr(9)) for c in v)
    if isinstance(v, list):
        return any(_has_control_chars(x) for x in v)
    if isinstance(v, dict):
        return any(_has_control_chars(x) for x in v.values())
    return False


def check_guide(raw) -> tuple[dict | None, str | None]:
    """校验并清洗 guide.json：返回 (清洗后的内容, 不合法的原因)。未知的键丢弃，所有文本只当纯文本显示。"""
    if not isinstance(raw, dict):
        return None, "guide.json 必须是一个 JSON 对象"
    if _has_control_chars(raw):
        return None, "文本里有控制字符（Windows 路径里的反斜杠在 JSON 里要写成两个，否则会变成不可见字符）"
    out: dict = {}
    for k, limit in _GUIDE_TEXT.items():
        v = raw.get(k, "")
        if not isinstance(v, str) or len(v) > limit:
            return None, f"{k} 必须是不超过 {limit} 字的字符串"
        out[k] = v.strip()
    for k, (n, limit) in _GUIDE_LISTS.items():
        v = raw.get(k, [])
        if not isinstance(v, list) or len(v) > n or any(not isinstance(x, str) or not x.strip() or len(x) > limit for x in v):
            return None, f"{k} 必须是最多 {n} 条、每条不超过 {limit} 字的非空字符串列表"
        out[k] = [x.strip() for x in v]
    for k, (a, b, n, la, lb) in _GUIDE_PAIRS.items():
        v = raw.get(k, [])
        if not isinstance(v, list) or len(v) > n:
            return None, f"{k} 必须是最多 {n} 条的列表"
        items = []
        for x in v:
            if not isinstance(x, dict) or not all(isinstance(x.get(f), str) and x.get(f).strip() for f in (a, b))                     or len(x[a]) > la or len(x[b]) > lb:
                return None, f"{k} 每条都要有非空的 {a}（≤{la} 字）和 {b}（≤{lb} 字）"
            items.append({a: x[a].strip(), b: x[b].strip()})
        out[k] = items
    if not out["summary"]:
        return None, "summary（一句话说明这个应用给谁用、做什么）不能为空"
    return out, None


def load_guide(d: Path) -> dict | None:
    f = d / "guide.json"
    if not f.is_file():
        return None
    try:
        guide, bad = check_guide(json.loads(f.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as e:
        guide, bad = None, str(e)
    if bad:
        log.warning("应用 %s 的 guide.json 无效，说明不显示（应用照常可用）：%s", d.name, bad)
    return guide


@dataclass
class App:
    id: str
    name: str
    version: str
    description: str
    entry: str
    requires: dict = field(default_factory=dict)
    setup_args: list[str] = field(default_factory=list)  # 首次（或每次）启动前先跑一遍的初始化参数，可为空
    start_args: list[str] = field(default_factory=list)
    # 每次打开前先用新包入口跑一遍的命令（由应用自己判断要不要停掉正在运行的旧版本：旧且空闲才停，有任务在跑退出码 3）；空 = 不自动升级
    upgrade_args: list[str] = field(default_factory=list)
    zip_path: Path = Path()
    guide: dict | None = None   # 接入说明（guide.json），没有或写错就是 None


def _load(d: Path) -> App | None:
    try:
        meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
        a = App(id=str(meta["id"]), name=str(meta["name"]), version=str(meta["version"]),
                description=str(meta.get("description", "")), entry=str(meta["entry"]),
                requires=dict(meta.get("requires") or {}), setup_args=[str(x) for x in meta.get("setup_args") or []],
                start_args=[str(x) for x in meta.get("start_args") or []],
                upgrade_args=[str(x) for x in meta.get("upgrade_args") or []],
                zip_path=d / f"{meta['version']}.zip")
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("应用 %s 的 app.json 无效，已跳过：%s", d.name, e)
        return None
    if (bad := _check_requires(a.requires)):
        log.warning("应用 %s 的 requires 不合法，已跳过：%s", d.name, bad)
        return None
    if a.id != d.name or not APP_ID.match(a.id) or not a.entry or not a.version or "/" in a.version or ".." in a.version:
        log.warning("应用 %s 的 id / 入口 / 版本不合法，已跳过", d.name)
        return None
    if not a.zip_path.is_file():
        log.warning("应用 %s 缺少 %s，已跳过", a.id, a.zip_path.name)
        return None
    a.guide = load_guide(d)
    return a


def list_apps() -> list[App]:
    root = Path(settings.apps_dir)
    if not root.is_dir():
        return []
    return [a for d in sorted(root.iterdir()) if d.is_dir() and (a := _load(d))]


def get_app(app_id: str) -> App | None:
    """按注册表查应用；输入只用来在已注册的 id 里比对，不参与路径拼接。"""
    return next((a for a in list_apps() if a.id == app_id), None) if app_id else None


_HASHES: dict[str, tuple[int, int, str]] = {}


def sha256_of(path: Path) -> str:
    st = path.stat()
    hit = _HASHES.get(str(path))
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _HASHES[str(path)] = (st.st_mtime_ns, st.st_size, h.hexdigest())
    return h.hexdigest()


def _sign(app_id: str, version: str, exp: int) -> str:
    return hmac.new(settings.file_secret.encode(), f"app:{app_id}/{version}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_zip_url(a: App, ttl: int = LINK_TTL) -> str:
    exp = int(time.time()) + ttl
    return f"{settings.public_url.rstrip('/')}/api/apps/{a.id}/{a.version}.zip?" + urlencode({"exp": exp, "sig": _sign(a.id, a.version, exp)})


def verify_zip_request(app_id: str, version: str, exp: int, sig: str) -> Path | None:
    a = get_app(app_id)
    if not a or not settings.file_secret or version != a.version or exp < time.time():
        return None
    return a.zip_path if hmac.compare_digest(_sign(a.id, a.version, exp), sig) else None
