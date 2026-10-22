"""复盘经验沉淀流程的端到端测试：员工 A 的 agent 提交到「复盘总结」→ 主管审核采纳 → 员工 B 的 agent 检索得到；没有权限的岗位看不到。
真实 Casdoor 登录 + 真实 MCP HTTP + 真实控制台接口。在 console-api 容器里运行；会创建并最后删除测试账号和测试数据。
（agent「先问员工再提交」的行为由真实 CodeBuddy 另行验证，见 docs/proposals.md）"""
import base64, hashlib, json, secrets, time
from urllib.parse import parse_qs, urlparse

import httpx

from app import db, kbmeta, kbstore, proposals as pr, ragflow, skillstore
from app.config import settings
from app.members_admin import MemberAdmin

ok = bad = 0


def check(label, cond, extra=""):
    global ok, bad
    ok += bool(cond)
    bad += (not cond)
    print(("PASS" if cond else "FAIL"), label, "" if cond else f"  → {extra}")


def console_login(username, password):
    cas = httpx.Client(base_url=settings.casdoor_endpoint, timeout=20)
    console = httpx.Client(base_url="http://localhost:8100", timeout=30)
    url = console.get("/api/auth/login").json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    r = cas.post("/api/login", params={"clientId": q["client_id"], "responseType": "code", "redirectUri": q["redirect_uri"], "scope": q["scope"], "state": q["state"]},
                 json={"application": "hub-console", "organization": settings.casdoor_org, "username": username, "password": password, "type": "code", "autoSignin": False}).json()
    assert r.get("status") == "ok", r
    assert console.post("/api/auth/callback", json={"code": r["data"], "state": q["state"]}).status_code == 200
    return console


def agent_token(username, password):
    """员工 agent 的登录：授权码 + PKCE（与 hub_agent.py 一致）。"""
    cfg = httpx.get("http://localhost:8100/api/agent/config").json()
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
    return t["access_token"], cfg["mcp_url"]


class Mcp:
    def __init__(self, token, url):
        self.http, self.url, self.n = httpx.Client(timeout=60), url, 0
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json", "X-Hub-Trace-Id": "e2e-" + secrets.token_hex(3)}
        r = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}})
        if sid := r.headers.get("mcp-session-id"):
            self.h["Mcp-Session-Id"] = sid
        self.http.post(self.url, headers=self.h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _rpc(self, method, params):
        self.n += 1
        return self.http.post(self.url, headers=self.h, json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})

    def call(self, tool, **args):
        r = self._rpc("tools/call", {"name": tool, "arguments": args})
        body = r.text
        data = next((json.loads(l[5:]) for l in body.splitlines() if l.startswith("data:")), None) if "data:" in body else r.json()
        res = data["result"]
        return "".join(c.get("text", "") for c in res.get("content", []))


a = MemberAdmin()
org = settings.casdoor_org
kbmeta.refresh(force=True)
from app import content  # noqa: E402

KB_NAME = "复盘总结"
kb_id = next((k for k, v in content.KB_REGISTRY.items() if v["name"] == KB_NAME), None)
assert kb_id, "还没有「复盘总结」知识库"
UNIQUE = "银河骑士" + secrets.token_hex(2)  # 一个只会出现在测试文档里的词，用来确认检索命中的就是它
DOC = "zz复盘 2026-10 第3周 标题结构"

users = {"zz-test-emp": ("测试员工A", "ops"), "zz-test-emp2": ("测试员工B", "ops"), "zz-test-mgr": ("测试主管", "ops"), "zz-test-fin": ("测试财务", "finance")}
pw = {}
for name, (disp, dept) in users.items():
    out = a.create(name, disp, dept, title="自动测试")
    pw[name] = out["initial_password"]
    u = a.get_user(name)
    u["needUpdatePassword"] = False
    a._save(u)
db.set_dept_managers(org, "ops", ["zz-test-mgr"])
with db.connect() as c:
    snap_docs = {(r["kb_id"], r["name"]) for r in c.execute("SELECT kb_id, name FROM kb_docs").fetchall()}
try:
    emp = Mcp(*agent_token("zz-test-emp", pw["zz-test-emp"]))
    emp2 = Mcp(*agent_token("zz-test-emp2", pw["zz-test-emp2"]))
    fin = Mcp(*agent_token("zz-test-fin", pw["zz-test-fin"]))
    mgr = console_login("zz-test-mgr", pw["zz-test-mgr"])

    who = json.loads(emp.call("whoami"))
    check("运营员工的岗位包里有「复盘总结」知识库", KB_NAME in who["knowledge_bases"], who["knowledge_bases"])
    check("财务员工的岗位包里没有它", KB_NAME not in json.loads(fin.call("whoami"))["knowledge_bases"])

    # 1. 员工 A 的 agent 在员工确认后提交（agent 侧的「先问再提」由真实 CodeBuddy 另行验证）
    content_md = f"# {DOC}\n\n> 来源：测试账号，数据范围：10/14–10/20，整理人：测试员工A\n\n## 数据依据\n符合结构的 2 篇平均阅读 10,450、互动率 12.2%；不符合的 2 篇平均阅读 2,650、互动率 4.4%。\n\n## 经验结论\n- 继续做：标题带数字和具体场景（依据：{UNIQUE}）\n- 停止做：泛清单式标题\n"
    r = emp.call("propose_improvement", kind="new_doc", target=DOC, knowledge_base=KB_NAME, summary="沉淀：标题结构复盘结论", rationale="周复盘数据显示标题结构差异最明显",
                 proposed_content=content_md, evidence="周复盘，4 篇样本")
    check("员工 agent 提交沉淀建议", "proposal_id" in r and "该部门主管" in r, r)
    pid = json.loads(r)["proposal_id"]
    r = emp.call("propose_improvement", kind="new_doc", target=DOC, knowledge_base=KB_NAME, summary="重复提交", proposed_content=content_md)
    check("同一份文档不能重复提交（待处理中）", "已经有一条待处理" in r, r)
    r = fin.call("propose_improvement", kind="new_doc", target=DOC + "财务", knowledge_base=KB_NAME, summary="越权", proposed_content=content_md)
    check("财务员工不能往「复盘总结」提建议", "proposal_id" not in r, r)
    check("提交后文档还不在库里（要等主管审核）", DOC not in [d["id"] for d in mgr.get(f"/api/knowledge-bases/{kb_id}/documents").json()])
    check("提交后员工 B 也检索不到它", UNIQUE not in emp2.call("search_knowledge", query=UNIQUE, knowledge_base=KB_NAME))

    # 2. 主管审核
    d = mgr.get(f"/api/proposals/{pid}").json()
    check("主管在「改进建议」里看到这条", d["id"] == pid and d["kb_name"] == KB_NAME and d["kind"] == "new_doc" and UNIQUE in d["proposed_content"], d.get("kb_name"))
    r = mgr.post(f"/api/proposals/{pid}/accept", json={"note": "流程验证"})
    check("主管采纳", r.status_code == 200 and r.json()["published"], r.text)
    check("检索索引同步成功", r.json().get("synced") is True, r.text)

    # 3. 入库后：控制台可见、其他员工的 agent 检索得到
    docs = {x["id"]: x for x in mgr.get(f"/api/knowledge-bases/{kb_id}/documents").json()}
    check("文档出现在知识库里", DOC in docs and docs[DOC]["version"] == 1, list(docs))
    hit = ""
    for _ in range(30):
        hit = emp2.call("search_knowledge", query=UNIQUE, knowledge_base=KB_NAME)
        if UNIQUE in hit:
            break
        time.sleep(3)
    check("另一位员工的 agent 检索到这篇复盘（RAGFlow）", UNIQUE in hit, hit[:300])
    check("没有权限的财务员工检索不到", UNIQUE not in fin.call("search_knowledge", query=UNIQUE, knowledge_base=KB_NAME) and UNIQUE not in fin.call("search_knowledge", query=UNIQUE))
    mine = {m["proposal_id"]: m for m in json.loads(emp.call("my_proposals"))}
    check("提出人看到「已采纳」", mine[pid]["status"] == "已采纳", mine.get(pid))
    wk = mgr.get("/api/work/report?days=1").json()
    check("提出人这次沉淀记成一项成果", any(i["kind"] == "改进建议" and i["user_name"] == "zz-test-emp" for i in wk["items"]), [i["kind"] for i in wk["items"]])
    check("主管能看到入库后的文档内容", "经验结论" in mgr.get(f"/api/knowledge-bases/{kb_id}/documents/{DOC}").json()["content"])
finally:
    with db.connect() as c:
        c.execute("DELETE FROM proposals WHERE proposer LIKE 'zz-test-%'")
        c.execute("DELETE FROM work_items WHERE user_name LIKE 'zz-test-%'")
        for (kb, name) in [(r["kb_id"], r["name"]) for r in c.execute("SELECT kb_id, name FROM kb_docs").fetchall()]:
            if (kb, name) not in snap_docs:
                c.execute("DELETE FROM kb_docs WHERE kb_id = %s AND name = %s", (kb, name))
    cl = ragflow.from_settings()
    if cl is not None:
        ds = cl.find_dataset(f"hub-{kb_id}")
        if ds:
            for d in cl.list_documents(ds):
                if d["name"].startswith("zz"):
                    cl.delete_documents(ds, [d["id"]])
    for n in users:
        try:
            a.remove(n, acting="admin")
        except Exception as e:  # noqa: BLE001
            print("rm", n, e)
        db.drop_user_roles(org, n)
    db.set_dept_managers(org, "ops", [])
print(f"\n{ok} 通过, {bad} 失败")
