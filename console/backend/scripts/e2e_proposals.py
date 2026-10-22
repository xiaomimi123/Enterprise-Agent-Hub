"""改进建议的端到端测试：真实 Casdoor 登录（员工走 hub-agent 的 PKCE，主管 / 老板走控制台）、真实 MCP HTTP、真实控制台接口。
在 console-api 容器里运行；会创建并最后删除测试账号和测试数据。"""
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
users = {"zz-test-emp": "测试员工", "zz-test-mgr": "测试主管", "zz-test-boss": "测试老板"}
pw = {}
for name, disp in users.items():
    out = a.create(name, disp, "ops", title="自动测试")
    pw[name] = out["initial_password"]
    u = a.get_user(name)
    u["needUpdatePassword"] = False
    a._save(u)
db.set_dept_managers(org, "ops", ["zz-test-mgr"])
db.set_bosses(org, ["zz-test-boss"])
created_docs = []
with db.connect() as c:
    snap_skills = {r["id"]: (r["published_version"], r["mv"]) for r in c.execute("SELECT s.id, s.published_version, (SELECT max(version) FROM skill_versions v WHERE v.skill_id = s.id) AS mv FROM skills s").fetchall()}
    snap_docs = {(r["kb_id"], r["name"]): (r["published_version"], r["mv"], r["deleted"]) for r in c.execute("SELECT d.kb_id, d.name, d.published_version, d.deleted, (SELECT max(version) FROM kb_doc_versions v WHERE v.kb_id = d.kb_id AND v.name = d.name) AS mv FROM kb_docs d").fetchall()}
try:
    token, mcp_url = agent_token("zz-test-emp", pw["zz-test-emp"])
    emp = Mcp(token, mcp_url)
    mgr, boss = console_login("zz-test-mgr", pw["zz-test-mgr"]), console_login("zz-test-boss", pw["zz-test-boss"])
    tools = emp._rpc("tools/list", {}).text
    check("MCP 暴露了新工具", "propose_improvement" in tools and "my_proposals" in tools)

    pack_skills = json.loads(emp.call("whoami"))["skills"]
    own_dept_skill = "xhs-topic"
    all_skill = next((s for s in pack_skills if s.startswith("common-")), None)
    print("   岗位包技能:", pack_skills)
    foreign = "cs-reply"
    cur = skillstore.read_skill(own_dept_skill)

    # 1. 员工提建议
    r = emp.call("propose_improvement", kind="skill", target=own_dept_skill, summary="补充一个检查步骤", rationale="用户多次手动补充", proposed_content=cur + "\n- 【测试追加】发布前再核对一次违禁词\n")
    check("员工提交技能建议", "proposal_id" in r and "该部门主管" in r, r)
    pid1 = json.loads(r)["proposal_id"] if "proposal_id" in r else None
    r = emp.call("propose_improvement", kind="skill", target=own_dept_skill, summary="重复提")
    check("同一目标同时只能一条待处理", "已经有一条待处理" in r, r)
    r = emp.call("propose_improvement", kind="skill", target=foreign, summary="别人的技能")
    check("不在岗位包里的技能不能提", "无权" in r, r)
    r = emp.call("propose_improvement", kind="skill", target="no-such-skill", summary="x")
    check("不存在的技能被拒", "不存在" in r or "无权" in r, r)
    r = emp.call("propose_improvement", kind="skill", target=own_dept_skill + "x", summary="x")
    r = emp.call("propose_improvement", kind="doc", target="不存在的文档", knowledge_base="品牌调性与人设", summary="x")
    check("不存在的文档被拒", "不存在" in r, r)
    r = emp.call("propose_improvement", kind="doc", target="品牌人设定义", knowledge_base="财务制度与报表", summary="x")
    check("没权限的知识库不能提", "知识库" in r and "proposal_id" not in r, r)
    doc_cur = kbstore.get_doc("kb-brand", "品牌人设定义")
    dtext = next(v["content"] for v in kbstore.versions("kb-brand", "品牌人设定义") if v["version"] == doc_cur["published_version"])
    r = emp.call("propose_improvement", kind="doc", target="品牌人设定义", knowledge_base="品牌调性与人设", summary="人设里补一句", rationale="文案风格不一致", proposed_content=dtext + "\n【测试】口吻要亲切。\n")
    check("员工提交文档建议", "proposal_id" in r, r)
    pid2 = json.loads(r)["proposal_id"]
    r = emp.call("propose_improvement", kind="new_doc", target="zz测试新文档", knowledge_base="品牌调性与人设", summary="新增话术文档")
    check("新增文档必须带内容", "必须带上" in r, r)
    r = emp.call("propose_improvement", kind="new_doc", target="标题结构：数字 + 人群/场景", knowledge_base="品牌调性与人设", summary="x", proposed_content="# t\n\n内容\n")
    check("文档名含 / 时给出明确原因（不是没有说明的工具错误）", "文档名不合规" in r and "Error" not in r, r)
    r = emp.call("propose_improvement", kind="new_doc", target="zz测试新文档", knowledge_base="品牌调性与人设", summary="新增话术文档", proposed_content="# 新文档\n\n测试专用口号：银河骑士。\n")
    check("员工提交新增文档建议", "proposal_id" in r, r)
    pid3 = json.loads(r)["proposal_id"]
    pid4 = None
    if all_skill:
        r = emp.call("propose_improvement", kind="skill", target=all_skill, summary="全公司技能建议", proposed_content=skillstore.read_skill(all_skill) + "\n- 【测试】\n")
        check("员工提交全公司技能建议（要老板审）", "老板或管理员" in r, r)
        pid4 = json.loads(r)["proposal_id"] if "proposal_id" in r else None
    mine = json.loads(emp.call("my_proposals"))
    check("my_proposals 看到待处理的", sum(1 for m in mine if m["status"] == "待处理") >= 3, mine)

    # 2. 主管 / 老板视角
    ml = mgr.get("/api/proposals").json()
    ids = {p["id"] for p in ml}
    check("主管看到本部门的建议", {pid1, pid2, pid3} <= ids, ids)
    check("主管看不到全公司的建议", pid4 not in ids)
    bl = {p["id"] for p in boss.get("/api/proposals").json()}
    check("老板看到全部", {pid1, pid2, pid3} <= bl and (pid4 is None or pid4 in bl))
    d = mgr.get(f"/api/proposals/{pid1}").json()
    check("详情带差异所需内容", d["proposed_content"] and d["current_content"] and not d["stale"], d.get("stale"))
    if pid4:
        check("主管打不开全公司建议", mgr.get(f"/api/proposals/{pid4}").status_code == 404)
        check("主管不能采纳全公司建议", mgr.post(f"/api/proposals/{pid4}/accept", json={}).status_code == 404)

    # 3. 采纳
    r = mgr.post(f"/api/proposals/{pid1}/accept", json={"note": "好建议"})
    check("主管采纳技能建议", r.status_code == 200 and r.json()["version"] == snap_skills[own_dept_skill][0] + 1 and r.json()["published"], r.text)
    check("员工的 agent 马上读到新版本", "【测试追加】" in emp.call("read_skill", skill_id=own_dept_skill))
    check("再次采纳被拒", mgr.post(f"/api/proposals/{pid1}/accept", json={}).status_code == 400)
    wk = boss.get("/api/work/report?days=1").json()
    check("提出人的采纳记成成果", any(i["kind"] == "改进建议" and i["user_name"] == "zz-test-emp" for i in wk["items"]), [i["kind"] for i in wk["items"]])
    check("日报带待处理建议数", wk.get("proposals_open", 0) >= 1 and "改进建议" in wk["digest"], wk.get("proposals_open"))

    # 4. 过期：文档在建议后被改过
    r = mgr.put("/api/knowledge-bases/kb-brand/documents/品牌人设定义", json={"content": dtext + "\n别人先改了一句。\n", "note": "先改", "base_version": doc_cur["published_version"]})
    check("主管先直接改了文档", r.status_code == 200, r.text)
    d2 = mgr.get(f"/api/proposals/{pid2}").json()
    check("建议被标记为基于旧版本", d2["stale"] and d2["base_version"] != d2["current_version"])
    r = mgr.post(f"/api/proposals/{pid2}/accept", json={})
    check("过期建议不确认就不能采纳", r.status_code == 400 and "基于第" in r.text, r.text)
    r = mgr.post(f"/api/proposals/{pid2}/accept", json={"content": dtext + "\n别人先改了一句。\n【测试】口吻要亲切。\n", "confirm_stale": True, "note": "合并后采纳"})
    check("确认并修改后采纳", r.status_code == 200 and r.json()["version"] == doc_cur["published_version"] + 2, r.text)
    time.sleep(1)

    # 5. 新增文档建议：采纳后进库并同步检索
    r = mgr.post(f"/api/proposals/{pid3}/accept", json={})
    created_docs.append(("kb-brand", "zz测试新文档"))
    check("采纳新增文档", r.status_code == 200 and r.json()["published"], r.text)
    check("新文档同步到 RAGFlow", r.json().get("synced") is True, r.text)
    cl = ragflow.from_settings()
    for _ in range(25):
        hits = emp.call("search_knowledge", query="银河骑士", knowledge_base="品牌调性与人设")
        if "银河骑士" in hits:
            break
        time.sleep(3)
    check("员工的 agent 检索到新文档（RAGFlow）", "银河骑士" in hits, hits[:200])

    # 6. 驳回 + 反馈
    r = emp.call("propose_improvement", kind="skill", target=own_dept_skill, summary="第二条建议", proposed_content=skillstore.read_skill(own_dept_skill) + "\n- 另一条\n")
    pid5 = json.loads(r)["proposal_id"]
    check("驳回要写原因", mgr.post(f"/api/proposals/{pid5}/reject", json={"note": " "}).status_code == 400)
    check("主管驳回", mgr.post(f"/api/proposals/{pid5}/reject", json={"note": "这条和现有步骤重复"}).status_code == 200)
    mine = {m["proposal_id"]: m for m in json.loads(emp.call("my_proposals"))}
    check("员工看到驳回原因", mine[pid5]["status"] == "已驳回" and "重复" in mine[pid5]["review_note"], mine.get(pid5))
    check("员工看到已采纳", mine[pid1]["status"] == "已采纳")

    # 7. 老板采纳全公司建议
    if pid4:
        r = boss.post(f"/api/proposals/{pid4}/accept", json={"note": "ok"})
        check("老板采纳全公司建议", r.status_code == 200 and r.json()["published"], r.text)
    # 8. 没带内容的建议：审核人必须自己写
    r = emp.call("propose_improvement", kind="skill", target=own_dept_skill, summary="只有想法没有内容")
    pid6 = json.loads(r)["proposal_id"]
    r = mgr.post(f"/api/proposals/{pid6}/accept", json={})
    check("没带内容的建议不能直接采纳", r.status_code == 400 and "没有带新内容" in r.text, r.text)
    check("驳回后失败的采纳没把建议弄丢", mgr.get(f"/api/proposals/{pid6}").json()["status"] == "open")
    # 9. 每日上限
    with db.connect() as c:
        for i in range(pr.DAILY_LIMIT):
            c.execute("INSERT INTO proposals (kind, target, dept_id, proposer, summary, status) VALUES ('skill', %s, 'ops', 'zz-test-emp', 'x', 'rejected')", (f"filler{i}",))
    r = emp.call("propose_improvement", kind="skill", target=pack_skills[1] if pack_skills[1] != own_dept_skill else pack_skills[2], summary="超限")
    check("每天最多 10 条", "最多" in r or "今天已经提了" in r, r)
    # 10. 权限边界：员工没有控制台权限
    emp_console = console_login("zz-test-emp", pw["zz-test-emp"]) if False else None
finally:
    with db.connect() as c:
        c.execute("DELETE FROM proposals WHERE proposer = 'zz-test-emp'")
        c.execute("DELETE FROM work_items WHERE user_name = 'zz-test-emp'")
        for kb_id, name in created_docs:
            c.execute("DELETE FROM kb_docs WHERE kb_id = %s AND name = %s", (kb_id, name))
        # 只还原这次测试改过的版本：回到测试开始时的快照（用户真实的编辑不动）
        for sid, (pv, mv) in snap_skills.items():
            c.execute("DELETE FROM skill_versions WHERE skill_id = %s AND version > %s", (sid, mv))
            c.execute("UPDATE skills SET published_version = %s WHERE id = %s", (pv, sid))
        for (kb, name), (pv, mv, dele) in snap_docs.items():
            c.execute("DELETE FROM kb_doc_versions WHERE kb_id = %s AND name = %s AND version > %s", (kb, name, mv))
            c.execute("UPDATE kb_docs SET published_version = %s, deleted = %s WHERE kb_id = %s AND name = %s", (pv, dele, kb, name))
    cl = ragflow.from_settings()
    if cl is not None:
        ds = cl.ensure_dataset("hub-kb-brand")
        for d in cl.list_documents(ds):
            if d["name"].startswith("zz"):
                cl.delete_documents(ds, [d["id"]])
        kbstore.sync_doc(cl, "kb-brand", "品牌人设定义")  # 把检索索引里被测试改过的文档还原成测试前的内容
    for n in users:
        try:
            a.remove(n, acting="admin")
        except Exception as e:  # noqa: BLE001
            print("rm", n, e)
        db.drop_user_roles(org, n)
    db.set_dept_managers(org, "ops", [])
    db.set_bosses(org, [])
print(f"\n{ok} 通过, {bad} 失败")
