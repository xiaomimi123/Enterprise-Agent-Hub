"""真实数据源（casdoor 模式）。

| 模块 | 来源 |
|---|---|
| 部门与成员 | Casdoor（生产环境由钉钉同步进 Casdoor），缓存 30 秒 |
| 岗位包、成员分配 | 中枢数据库 role_packs / role_assignments |
| 审计链路 | 中枢数据库 audit_events（由 MCP Server 写入） |
| 技能 | skills/ 目录下的 SKILL.md |
| 知识库 | vault/ 目录（Obsidian），元数据见 content.KB_REGISTRY |
| 用量与成本 | New API 的调用日志（每个员工一个 key，按 key 名归属到人和部门）；未配置 New API 时为演示数据 |
| GPU 节点 | 中枢数据库 gpu_nodes / gpu_tasks（由 GPU 调度服务维护）；未配置节点时为演示数据 |

成员没有分配记录时，按部门的默认岗位包（控制台「部门与角色」配置，其次 policy.DEFAULT_ROLE_PACKS），都没有时用「通用办公」。
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import httpx

from .. import content, db, kbmeta, kbstore, metering, presence, skillstore
from ..config import settings
from ..newapi import NewApi, NewApiError, user_from_token_name
from ..policy import default_pack_id
from .demo import DemoProvider, NotFound

UNASSIGNED = "unassigned"


class CasdoorProvider(DemoProvider):
    mode = "casdoor"
    cache_seconds = 30
    # 真实审计数据不需要像演示数据那样按抽样比例放大
    sample_scale = 1

    def __init__(self) -> None:
        super().__init__()
        self.org = settings.casdoor_org
        self.http = httpx.Client(
            base_url=settings.casdoor_endpoint,
            auth=(settings.casdoor_client_id, settings.casdoor_client_secret),
            timeout=10,
        )
        self._org_synced_at = 0.0
        self._skills_imported = False
        self._kb_imported = False
        self.newapi = NewApi()
        self._usage_synced_at = 0.0
        self._price_table: dict[str, tuple[float, float]] = {}   # 最近一次读到的模型价格，链路花费重算用
        self._model_logs: list[dict] = []
        self._users: dict[str, dict] = {}
        self._groups: list[dict] = []
        db.init_schema()

    # ---- Casdoor API ----
    def _get(self, path: str, **params) -> object:
        body = self.http.get(path, params=params).json()
        if body.get("status") != "ok":
            raise RuntimeError(f"Casdoor {path} 失败：{body.get('msg')}")
        return body.get("data")

    def _sync_org(self, force: bool = False) -> None:
        if not force and time.time() - self._org_synced_at < self.cache_seconds:
            return
        org = self._get("/api/get-organization", id=f"admin/{self.org}") or {}
        self._groups = self._get("/api/get-groups", owner=self.org) or []
        users = [u for u in (self._get("/api/get-users", owner=self.org) or []) if not u.get("isDeleted")]
        self._users = {u["name"]: u for u in users}
        self.d["company"] = org.get("displayName") or self.org
        self._org_synced_at = time.time()

    def _sync(self, force_org: bool = False) -> None:
        """组织数据按缓存刷新；岗位包、分配、审计每次都从数据库读取，保证与 MCP Server 一致。"""
        self._sync_org(force_org)
        dept_names = {g["name"]: g.get("displayName") or g["name"] for g in self._groups}
        dept_names[UNASSIGNED] = "未分配部门"
        dept_names["all"] = "全公司"

        packs = db.role_packs()
        pack_ids = {p["id"] for p in packs}
        assigned = db.assignments(self.org)
        defaults = db.dept_defaults(self.org)

        members = []
        presence.sync_from_gateway(self.org)   # 模型网关里 5 分钟内调用过中枢模型的人也算在线（20 秒缓存）
        seen, now = db.presence_rows(self.org), datetime.now().astimezone()
        try:
            last_event = db.last_event_by_user(self.org)
        except Exception:  # noqa: BLE001 读不到审计时「最近活跃」退回登录时间 / 在线记录
            last_event = {}
        for u in self._users.values():
            group = next((g.split("/", 1)[-1] for g in (u.get("groups") or []) if g.split("/", 1)[-1] in dept_names), UNASSIGNED)
            pack = assigned.get(u["name"])
            members.append({
                "id": u["name"],
                "name": u.get("displayName") or u["name"],
                "dept": group,
                "dept_name": dept_names[group],
                "title": u.get("title") or "",
                "role_pack": pack if pack in pack_ids else default_pack_id(group, defaults),
                **presence.member_agent(seen.get(u["name"]), now),
                "dingtalk_bound": bool(u.get("dingtalk")),
                "enabled": not u.get("isForbidden"),
                "must_change_password": bool(u.get("needUpdatePassword")),
                "is_admin": bool(u.get("isAdmin")),
                "phone": u.get("phone") or "",
                "email": u.get("email") or "",
                "last_active": presence.latest_activity(u.get("lastSigninTime") or u.get("createdTime"), (seen.get(u["name"]) or {}).get("last_seen"), last_event.get(u["name"])),
            })

        departments = []
        for g in [*self._groups, {"name": UNASSIGNED}]:
            dm = [m for m in members if m["dept"] == g["name"]]
            if g["name"] == UNASSIGNED and not dm:
                continue
            departments.append({
                "id": g["name"], "name": dept_names[g["name"]], "member_count": len(dm),
                "leader": dm[0]["name"] if dm else "", "online": sum(1 for m in dm if m["agent_status"] == "在线"),
                "role_pack": default_pack_id(g["name"], defaults),
            })
        departments.sort(key=lambda x: (x["id"] == UNASSIGNED, -x["member_count"], x["name"]))

        self.d["member_names"] = {m["id"]: m["name"] for m in members}
        events = db.recent_audit(self.org, days=7)
        traces = db.traces_from_events(events, dept_names)
        self.d.update({
            "dept_names": dept_names,
            "members": members,
            "departments": departments,
            "role_packs": packs,
            "traces": traces,
            "skills": self._skills(events),
            "knowledge_bases": self._knowledge_bases(events),
        })
        self._sync_usage()
        db.attach_model_calls(traces, self._model_logs, self.org, settings.usd_cny,
                              quota_of=lambda lg: self.newapi.repriced_quota(lg, self._price_table))   # 链路里的模型花费也按当前价格重算
        self._sync_gpu()

    def _sync_gpu(self) -> None:
        nodes = db.gpu_nodes()
        if not nodes:
            return
        stats = db.gpu_task_stats()
        queued = stats.get("_queued", {}).get("n", 0)
        workflows = [p.stem for p in sorted(Path(settings.workflows_dir).glob("*.json"))]
        names = {"image-gen": "文生图", "video-h3": "文生视频", "video-h3-i2v": "图生视频"}
        out = []
        for n in nodes:
            st = stats.get(n["id"], {})
            running = st.get("running", 0) > 0
            used = (1 - n["vram_free"] / n["vram_total"]) * 100 if n["vram_total"] else 0
            out.append({
                "id": n["id"], "name": n["name"], "gpu": n["gpu"] or "未知显卡",
                "workflows": [names.get(w, w) for w in workflows],
                "status": "离线" if not n["online"] else ("忙碌" if running else "空闲"),
                "queue": queued, "jobs_today": st.get("done_today", 0),
                "utilization": round(used), "online": n["online"],
            })
        self.d["gpu_nodes"] = out
        for svc in self.d["services"]:
            if svc["name"] == "任务队列":
                svc["status"] = "正常" if any(n["online"] for n in nodes) else "异常"
                svc["component"] = f"GPU 调度 · {sum(n['online'] for n in nodes)}/{len(nodes)} 节点在线"

    def _sync_usage(self) -> None:
        """用 New API 的调用日志替换演示用量（缓存 60 秒）。"""
        if not self.newapi.configured or time.time() - self._usage_synced_at < 60:
            return
        try:
            logs = self.newapi.logs(days=30)
        except (NewApiError, httpx.HTTPError):
            return  # New API 暂时不可用时保留上一次的数据
        self._model_logs = logs
        by_user = {m["id"]: m for m in self.d["members"]}
        daily: dict[tuple, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        per_member: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "calls": 0})
        models = {m["id"] for m in self.d["models"]}
        table = self.newapi.price_table(log.get("model_name") for log in logs)   # 花费按当前配置的价格重算（记录里的额度可能是价格没设好时记的，虚高）
        self._price_table = table
        for log in logs:
            user = user_from_token_name(log.get("token_name") or "", self.org)
            if not user:
                continue
            tokens = int(log.get("prompt_tokens") or 0) + int(log.get("completion_tokens") or 0)
            # New API 的额度单位：500000 = 1 美元；额度按当前价格重算（模型没配价格时才用记录里的）
            cost = self.newapi.repriced_quota(log, table) / 500000 * settings.usd_cny
            model = log.get("model_name") or "unknown"
            if model not in models:
                self.d["models"].append({"id": model, "name": model, "location": "模型网关", "rate": 0.0})
                models.add(model)
            day = datetime.fromtimestamp(log.get("created_at") or 0).date().isoformat()
            dept = by_user.get(user, {}).get("dept", UNASSIGNED)
            daily[(day, dept, model)]["tokens"] += tokens
            daily[(day, dept, model)]["cost"] += cost
            pm = per_member[user]
            pm["tokens"] += tokens
            pm["cost"] += cost
            pm["calls"] += 1
        self.d["usage_daily"] = [{"date": d, "dept": dept, "model": m, "tokens": v["tokens"], "cost": round(v["cost"], 4)}
                                 for (d, dept, m), v in sorted(daily.items())]
        self.d["member_usage"] = sorted([{
            "member_id": u, "member": by_user.get(u, {}).get("name", u), "dept_name": by_user.get(u, {}).get("dept_name", ""),
            "tokens": v["tokens"], "cost": round(v["cost"], 2), "calls": v["calls"],
        } for u, v in per_member.items()], key=lambda x: x["tokens"], reverse=True)
        self._usage_synced_at = time.time()

    def _skills(self, events: list[dict]) -> list[dict]:
        used = Counter(e["detail"] for e in events if e["tool"] == "skill.read" and e["result"] == "通过")
        if not self._skills_imported:  # 首次：把 skills/ 目录导入版本库（已有的不覆盖）
            skillstore.import_from_disk({v: k for k, v in self.d["dept_names"].items() if k not in ("all", UNASSIGNED)})
            self._skills_imported = True
        meta = skillstore.published_meta()
        out = []
        for s in skillstore.list_skills():
            m = meta.get(s["id"], {})
            out.append({
                **s,
                "dept_name": "全公司" if s["dept"] == "all" else self.d["dept_names"].get(s["dept"], s["dept"]),
                "version": str(s["version"]) if s["version"] else "—",
                "source": f"{s['id']}/SKILL.md" + (f" · 第 {s['version']} 版" if s["version"] else " · 未导入"),
                "status": "已发布",
                "author": m.get("author_name", ""),
                "pending": m.get("pending", 0),
                "used_7d": sum(n for d, n in used.items() if f"「{s['id']}」" in d),
                "content": skillstore.read_skill(s["id"]) or "",
            })
        return out

    def _knowledge_bases(self, events: list[dict]) -> list[dict]:
        kbmeta.refresh()
        if not self._kb_imported:  # 首次：把 vault/ 目录导入文档库（已有的不覆盖）
            kbstore.import_from_disk()
            self._kb_imported = True
        hits = [e["detail"] for e in events if e["tool"] == "kb.search" and e["result"] == "通过"]
        out = []
        for kid, kb in content.KB_REGISTRY.items():
            docs = kbstore.list_docs(kid)
            out.append({
                **kb,
                "dept_name": self.d["dept_names"].get(kb["dept"], kb["dept"]),
                "doc_count": len(docs),
                "chunk_count": sum(len([b for b in re.split(r"\n\s*\n", d["content"] or "") if b.strip()]) for d in docs),
                "queries_7d": sum(1 for h in hits if kb["name"] in h),
                "overdue": kbmeta.is_overdue(kb),
                "due_in_days": kbmeta.due_in_days(kb),
                "owner_name": (self.d.get("member_names") or {}).get(kb["owner"], kb["owner"]),
                "updated_at": max((d["updated_at"].isoformat() for d in docs), default=""),
            })
        return out

    def kb_documents(self, kb_id: str) -> list[dict]:
        self._sync()
        if kb_id not in content.KB_REGISTRY:
            raise NotFound("知识库不存在")
        return kbstore.ui_documents(kb_id)

    # ---- 覆盖：先同步，再复用演示数据源的计算 ----
    def overview(self):
        self._sync()
        data = super().overview()
        # 近 14 天的在线人数与拦截次数：来自在线记录和审计日志；今天的在线数用实时值（5 分钟窗口内）
        ops = presence.daily_ops(db.online_by_day(self.org, 14), db.denied_by_day(self.org, 14), datetime.now().astimezone().date())
        ops[-1]["online"] = max(ops[-1]["online"], data["stats"]["agents_online"])
        data["daily_ops"] = ops
        return data

    def departments(self):
        self._sync()
        return super().departments()

    def members(self, dept=None, q=None):
        self._sync()
        return super().members(dept, q)

    def role_packs(self):
        self._sync()
        return super().role_packs()

    def role_pack(self, role_pack_id):
        self._sync()
        return super().role_pack(role_pack_id)

    def update_role_pack(self, role_pack_id: str, patch: dict) -> dict:
        self._sync()
        rp = self._find(self.d["role_packs"], role_pack_id, "岗位包")
        allowed = {"skills", "knowledge_bases", "tools", "models", "monthly_quota",
                   "max_action_level", "external_access", "description", "status",
                   "model_mode", "gpu_quota_minutes", "apps"}
        db.upsert_role_pack(role_pack_id, {**rp, **{k: v for k, v in patch.items() if k in allowed and v is not None}})
        return self.role_pack(role_pack_id)

    def catalog(self):
        self._sync()
        data = super().catalog()
        # 岗位包可选的模型改为模型网关里真实启用的模型
        if self.newapi.configured:
            try:
                models = self.newapi.available_models()
            except (NewApiError, httpx.HTTPError):
                models = []
            if models:
                data["models"] = [{"id": m, "name": m, "location": "模型网关"} for m in models]
        return data

    def skills(self):
        self._sync()
        return super().skills()

    def skill(self, skill_id):
        self._sync()
        return super().skill(skill_id)

    def knowledge_bases(self):
        self._sync()
        return super().knowledge_bases()

    def traces(self, member_id=None, outcome=None, dept=None, q=None):
        self._sync()
        return super().traces(member_id, outcome, dept, q)

    def trace(self, trace_id):
        self._sync()
        return super().trace(trace_id)

    def usage(self, days=30):
        self._sync()
        return super().usage(days)

    def _hub_usage(self, days: int) -> dict:
        """中枢资源（真实数据）：审计事件 + GPU 任务。"""
        members, packs = self._usage_maps()
        return metering.hub_usage(db.recent_audit(self.org, days), db.gpu_tasks_since(self.org, days), members, packs)

    def assign_role_pack(self, member_id: str, role_pack_id: str) -> dict:
        self._sync()
        self._find(self.d["role_packs"], role_pack_id, "岗位包")
        if member_id not in self._users:
            raise NotFound(f"成员 {member_id} 不存在")
        db.assign(self.org, member_id, role_pack_id)
        return next(m for m in self.members() if m["id"] == member_id)
