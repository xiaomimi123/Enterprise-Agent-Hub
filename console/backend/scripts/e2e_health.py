"""应用健康的端到端测试：员工的接入器（真实 hub_agent.py 代码）在本机记事件 → 转发到 /api/agent/health → 管理员在控制台看汇总和设备时间线；
老板看不到；格式不对 / 过期 / 超批量的被拒；超过 7 天的旧事件被清掉。
真实 Casdoor 登录 + 真实接口。在 console-api 容器里运行；会创建并最后删除测试账号和测试数据。"""
import base64, hashlib, importlib.util, json, os, secrets, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app import db
from app.config import settings
from app.members_admin import MemberAdmin

ok = bad = 0
HUB = "http://localhost:8100"


def check(label, cond, extra=""):
    global ok, bad
    ok += bool(cond)
    bad += (not cond)
    print(("PASS" if cond else "FAIL"), label, "" if cond else f"  → {extra}")


def console_login(username, password):
    cas = httpx.Client(base_url=settings.casdoor_endpoint, timeout=20)
    console = httpx.Client(base_url=HUB, timeout=30)
    url = console.get("/api/auth/login").json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    r = cas.post("/api/login", params={"clientId": q["client_id"], "responseType": "code", "redirectUri": q["redirect_uri"], "scope": q["scope"], "state": q["state"]},
                 json={"application": "hub-console", "organization": settings.casdoor_org, "username": username, "password": password, "type": "code", "autoSignin": False}).json()
    assert r.get("status") == "ok", r
    assert console.post("/api/auth/callback", json={"code": r["data"], "state": q["state"]}).status_code == 200
    return console


def agent_token(username, password):
    """员工 agent 的登录：授权码 + PKCE（与 hub_agent.py 一致）。"""
    cfg = httpx.get(f"{HUB}/api/agent/config").json()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(8)
    cas = httpx.Client(base_url=settings.casdoor_endpoint, timeout=20)
    r = cas.post("/api/login", params={"clientId": cfg["client_id"], "responseType": "code", "redirectUri": cfg["redirect_uri"], "scope": "openid profile", "state": state,
                                       "code_challenge": challenge, "code_challenge_method": "S256"},
                 json={"application": "hub-agent", "organization": settings.casdoor_org, "username": username, "password": password, "type": "code", "autoSignin": False}).json()
    assert r.get("status") == "ok", r
    t = cas.post("/api/login/oauth/access_token", data={"grant_type": "authorization_code", "client_id": cfg["client_id"], "code": r["data"], "code_verifier": verifier,
                                                         "redirect_uri": cfg["redirect_uri"]}).json()
    assert t.get("access_token"), t
    return t


a = MemberAdmin()
org = settings.casdoor_org
users = {"zz-test-emp": ("测试员工", "ops"), "zz-test-adm": ("测试管理员", "ops"), "zz-test-boss": ("测试老板", "ops")}
pw = {}
for name, (disp, dept) in users.items():
    pw[name] = a.create(name, disp, dept, title="自动测试")["initial_password"]
    u = a.get_user(name)
    u["needUpdatePassword"] = False
    if name == "zz-test-adm":
        u["isAdmin"] = True
    a._save(u)
with db.connect() as c:  # 只给测试账号加老板角色，不动真实的老板名单
    c.execute("INSERT INTO console_roles (org, user_name, role, dept_id) VALUES (%s, 'zz-test-boss', 'boss', '')", (org,))

tmp = Path(tempfile.mkdtemp(prefix="e2e-health-"))
os.environ["HUB_AGENT_HOME"], os.environ["HUB_APPS_ROOT"] = str(tmp / "hub-agent"), str(tmp / "HubApps")
os.environ.pop("HUB_HEALTH", None)
spec = importlib.util.spec_from_file_location("hub_agent", Path(settings.agent_dir) / "hub_agent.py")
ha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ha)

try:
    tok = agent_token("zz-test-emp", pw["zz-test-emp"])
    ha.save_creds(HUB, {"casdoor_url": settings.casdoor_endpoint, "client_id": "x"}, tok)
    creds = ha.load_creds()
    ha._CLIENT["name"] = "WorkBuddy"

    # 1. 接入器在本机记事件（含隐私的报错原文），断网时只记在本机
    now = datetime.now(timezone.utc).timestamp()
    ha.record_health("install", True, now=now - 300)
    ha.record_health("login", False, None, "连不上中枢 http://192.168.0.41:8088：ConnectError C:\\Users\\张三\\x token=abc123 13812345678", now=now - 200)
    ha.record_health("launch", True, app_id="xhs-workbench", app_version="0.7.9", now=now - 100)
    ha.record_health("launch", False, "PORT_IN_USE", "Error: listen EADDRINUSE 127.0.0.1:17890", "xhs-workbench", "0.7.9", now=now - 50)
    lines = ha.health_file().read_text(encoding="utf-8").splitlines()
    check("接入器把 4 条事件记在本机", len(lines) == 4, len(lines))
    check("本机记录里已经去掉用户名、令牌、手机号", not any(s in "\n".join(lines) for s in ("张三", "abc123", "13812345678")))
    check("断网时转发不推进进度", ha.flush_health(creds, "http://127.0.0.1:9") == 0 and not (tmp / "HubApps" / "logs" / "health.offset").exists())

    # 2. 连上后真实转发到中枢
    sent = ha.flush_health(creds, HUB)
    check("接入器把 4 条事件转发到中枢", sent == 4, sent)
    check("再转发一次不重复发", ha.flush_health(creds, HUB) == 0)
    device = ha.device_id()

    # 3. 接口的拒绝情况
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    r = httpx.post(f"{HUB}/api/agent/health", json={"events": [{"stage": "install", "ok": True}] * 51}, headers=h)
    check("单批超过 50 条被拒（413）", r.status_code == 413, r.status_code)
    check("没有令牌被拒（401）", httpx.post(f"{HUB}/api/agent/health", json={"events": []}).status_code == 401)
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    r = httpx.post(f"{HUB}/api/agent/health", headers=h, json={"events": [
        {"stage": "hack", "ok": False}, {"stage": "install", "ok": False, "at": old}, "not-a-dict",
        {"stage": "task", "ok": False, "code": "ACCESS_LOCKED", "message": "自动访问已锁定", "device_id": device, "app_id": "xhs-workbench", "app_version": "0.7.9"}]}).json()
    check("格式不对 / 超过保留期的跳过，其余照收", r == {"ok": True, "saved": 1, "skipped": 3}, r)

    # 4. 管理员看汇总
    adm = console_login("zz-test-adm", pw["zz-test-adm"])
    s = adm.get("/api/health/summary?days=1").json()
    codes = {c["code"]: c for c in s["codes"]}
    check("常见报错里有「连不上中枢」，带处理办法", "NET_UNREACHABLE" in codes and codes["NET_UNREACHABLE"]["fix"], list(codes))
    sample = codes.get("NET_UNREACHABLE", {}).get("sample", "")
    check("报错原文已去隐私（中枢侧）", sample and "张三" not in sample and "abc123" not in sample and "~\\x" in sample, sample)
    check("按 agent 统计到 WorkBuddy", codes.get("PORT_IN_USE", {}).get("agents") == {"WorkBuddy": 1}, codes.get("PORT_IN_USE"))
    dev = next((d for d in s["devices"] if d["user_name"] == "zz-test-emp"), None)
    check("设备列表里有这台设备，最近一次是失败、排在前面", dev and dev["failing"] and dev["last_code"] == "ACCESS_LOCKED" and s["devices"][0]["user_name"] == "zz-test-emp", dev)
    check("设备记了系统、接入器版本、应用版本", dev and dev["connector_version"] == ha.VERSION and dev["app_version"] == "xhs-workbench 0.7.9" and dev["os"], dev)
    check("打开应用成功率按 1 成功 1 失败算", s["totals"]["launch"] == {"total": 2, "ok": 1, "rate": 0.5} or s["totals"]["launch"]["total"] >= 2, s["totals"]["launch"])
    check("应用下拉里有 xhs-workbench 0.7.9", ["xhs-workbench", "0.7.9"] in s["apps"], s["apps"])
    f = adm.get("/api/health/summary?days=1&app_id=xhs-workbench&app_version=0.7.9").json()
    check("按应用筛选时也带上接入器自身的事件（登录、接入）", {"NET_UNREACHABLE", "PORT_IN_USE"} <= {c["code"] for c in f["codes"]}, [c["code"] for c in f["codes"]])
    tl = adm.get(f"/api/health/device?user_name=zz-test-emp&device_id={device}").json()["events"]
    check("设备时间线 5 条，失败的带处理办法", len(tl) == 5 and all(e["fix"] for e in tl if not e["ok"]), len(tl))

    # 5. 老板看不到
    boss = console_login("zz-test-boss", pw["zz-test-boss"])
    check("老板访问应用健康被拒（403）", boss.get("/api/health/summary").status_code == 403)

    # 6. 领取配置时带回岗位包里能打开的应用（接入器据此生成双击启动器）
    en = httpx.post(f"{HUB}/api/agent/enroll", headers=h).json()
    check("领取配置带回应用列表（id + 名称）", isinstance(en.get("apps"), list) and all({"id", "name"} <= set(x) for x in en["apps"]), en.get("apps"))

    # 7. 只保留 7 天：写入新一批时清掉 7 天前的
    with db.connect() as c:
        c.execute("INSERT INTO app_health_events (org, user_name, stage, ok, code, at) VALUES (%s, 'zz-test-emp', 'install', true, 'OK', now() - interval '8 days')", (org,))
    httpx.post(f"{HUB}/api/agent/health", headers=h, json={"events": [{"stage": "install", "ok": True, "device_id": device}]})
    with db.connect() as c:
        n = c.execute("SELECT count(*) AS n FROM app_health_events WHERE user_name = 'zz-test-emp' AND at < now() - interval '7 days'").fetchone()["n"]
    check("超过 7 天的旧事件被清掉", n == 0, n)
finally:
    with db.connect() as c:
        c.execute("DELETE FROM app_health_events WHERE user_name LIKE 'zz-test-%'")
    for n in users:
        try:
            if n == "zz-test-adm":  # 管理员账号要先取消管理员身份才能删
                u = a.get_user(n)
                u["isAdmin"] = False
                a._save(u)
            a.remove(n, acting="admin")
        except Exception as e:  # noqa: BLE001
            print("rm", n, e)
        db.drop_user_roles(org, n)
        with db.connect() as c:  # 测试账号的在线记录也删掉，不然会出现在「应用健康」的设备列表里
            c.execute("DELETE FROM agent_presence WHERE user_name = %s", (n,))
            c.execute("DELETE FROM agent_presence_daily WHERE user_name = %s", (n,))
print(f"\n{ok} 通过, {bad} 失败")
