"""演示数据源：数据在内存里，重启后恢复初始状态。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from .. import demo_seed


class NotFound(KeyError):
    pass


class DemoProvider:
    mode = "demo"
    # 演示审计链路只是抽样，统计「今日任务」时按这个比例放大
    sample_scale = 9

    def __init__(self) -> None:
        self.d = demo_seed.build()

    # ---- 工具方法 ----
    def _find(self, items: list[dict], item_id: str, what: str) -> dict:
        for it in items:
            if it["id"] == item_id:
                return it
        raise NotFound(f"{what} {item_id} 不存在")

    def _member_count(self, role_pack_id: str) -> int:
        return sum(1 for m in self.d["members"] if m["role_pack"] == role_pack_id)

    def _summary_pack(self, rp: dict) -> dict:
        return {**rp, "dept_name": self.d["dept_names"][rp["dept"]], "member_count": self._member_count(rp["id"])}

    # ---- 总览 ----
    def overview(self) -> dict:
        d = self.d
        today = date.today().isoformat()
        month = today[:7]
        members = d["members"]
        traces_today = [t for t in d["traces"] if t["started_at"][:10] == today]
        usage_today = [u for u in d["usage_daily"] if u["date"] == today]
        usage_month = [u for u in d["usage_daily"] if u["date"][:7] == month]
        budget = sum(rp["monthly_quota"] * self._member_count(rp["id"]) for rp in d["role_packs"])

        trend = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        for u in d["usage_daily"]:
            if u["date"] >= (date.today() - timedelta(days=13)).isoformat():
                trend[u["date"]]["tokens"] += u["tokens"]
                trend[u["date"]]["cost"] += u["cost"]
        by_dept = defaultdict(float)
        for u in usage_month:
            by_dept[d["dept_names"][u["dept"]]] += u["cost"]

        pending = []
        for t in d["traces"]:
            for s in t["steps"]:
                if s["result"] == "待确认":
                    pending.append({"trace_id": t["id"], "member": t["member"], "dept_name": t["dept_name"],
                                    "tool": s["tool"], "detail": s["detail"], "time": s["time"]})
        denied = [t for t in d["traces"] if t["outcome"] == "被拦截"]

        return {
            "company": d["company"],
            "mode": self.mode,
            "stats": {
                "members": len(members),
                "agents_online": sum(1 for m in members if m["agent_status"] == "在线"),
                "agents_installed": sum(1 for m in members if m["agent_status"] != "未安装"),
                "calls_today": sum(len(t["steps"]) for t in traces_today) * self.sample_scale,
                "tasks_today": len(traces_today) * self.sample_scale,
                "tokens_today": sum(u["tokens"] for u in usage_today),
                "cost_today": round(sum(u["cost"] for u in usage_today), 2),
                "cost_month": round(sum(u["cost"] for u in usage_month), 2),
                "budget_month": budget,
                "denied_today": sum(1 for t in denied if t["started_at"][:10] == today),
                "pending_approvals": len(pending),
                "role_packs_live": sum(1 for rp in d["role_packs"] if rp["status"] == "已上线"),
                "role_packs_total": len(d["role_packs"]),
                "skills": len(d["skills"]),
                "knowledge_docs": sum(kb["doc_count"] for kb in d["knowledge_bases"]),
            },
            "trend": [{"date": k, "tokens": v["tokens"], "cost": round(v["cost"], 2)} for k, v in sorted(trend.items())],
            "daily_ops": d["daily_ops"][:-1] + [{**d["daily_ops"][-1],
                                                 "online": sum(1 for m in members if m["agent_status"] == "在线"),
                                                 "denied": sum(1 for t in denied if t["started_at"][:10] == today)}],
            "services": d["services"],
            "cost_by_dept": sorted([{"dept": k, "cost": round(v, 2)} for k, v in by_dept.items()],
                                   key=lambda x: x["cost"], reverse=True),
            "gpu_nodes": d["gpu_nodes"],
            "pending": pending[:6],
            "recent_denied": [{k: t[k] for k in ("id", "member", "dept_name", "summary", "started_at", "channel")}
                              for t in denied[:5]],
            "recent": [{k: t[k] for k in ("id", "member", "dept_name", "summary", "started_at", "outcome", "channel")}
                       for t in d["traces"][:12]],
        }

    # ---- 组织与成员 ----
    def departments(self) -> list[dict]:
        packs = {rp["id"]: rp["name"] for rp in self.d["role_packs"]}
        return [{**dep, "role_pack_name": packs[dep["role_pack"]]} for dep in self.d["departments"]]

    def members(self, dept: str | None = None, q: str | None = None) -> list[dict]:
        packs = {rp["id"]: rp["name"] for rp in self.d["role_packs"]}
        out = []
        for m in self.d["members"]:
            if dept and m["dept"] != dept:
                continue
            if q and q not in m["name"] and q not in m["title"]:
                continue
            out.append({**m, "role_pack_name": packs[m["role_pack"]]})
        return out

    def assign_role_pack(self, member_id: str, role_pack_id: str) -> dict:
        m = self._find(self.d["members"], member_id, "成员")
        self._find(self.d["role_packs"], role_pack_id, "岗位包")
        m["role_pack"] = role_pack_id
        return self.members(q=m["name"])[0]

    # ---- 岗位包 ----
    def role_packs(self) -> list[dict]:
        return [self._summary_pack(rp) for rp in self.d["role_packs"]]

    def role_pack(self, role_pack_id: str) -> dict:
        rp = self._find(self.d["role_packs"], role_pack_id, "岗位包")
        return {**self._summary_pack(rp),
                "members": [m for m in self.members() if m["role_pack"] == role_pack_id]}

    def update_role_pack(self, role_pack_id: str, patch: dict) -> dict:
        rp = self._find(self.d["role_packs"], role_pack_id, "岗位包")
        allowed = {"skills", "knowledge_bases", "tools", "models", "monthly_quota",
                   "max_action_level", "external_access", "description", "status"}
        rp.update({k: v for k, v in patch.items() if k in allowed and v is not None})
        return self.role_pack(role_pack_id)

    def catalog(self) -> dict:
        """岗位包编辑时可选的全部条目。"""
        d = self.d
        return {
            "skills": [{"id": s["id"], "name": s["name"], "dept_name": s["dept_name"], "status": s["status"]} for s in d["skills"]],
            "knowledge_bases": [{"id": k["id"], "name": k["name"], "dept_name": k["dept_name"],
                                 "classification": k["classification"]} for k in d["knowledge_bases"]],
            "tools": d["tools"],
            "models": d["models"],
        }

    # ---- 技能与知识库 ----
    def _skill_usage(self) -> dict[str, list[str]]:
        used = defaultdict(list)
        for rp in self.d["role_packs"]:
            for sid in rp["skills"]:
                used[sid].append(rp["name"])
        return used

    def skills(self) -> list[dict]:
        used = self._skill_usage()
        return [{**{k: v for k, v in s.items() if k != "content"}, "role_packs": used[s["id"]]} for s in self.d["skills"]]

    def skill(self, skill_id: str) -> dict:
        s = self._find(self.d["skills"], skill_id, "技能")
        return {**s, "role_packs": self._skill_usage()[skill_id]}

    def knowledge_bases(self) -> list[dict]:
        used = defaultdict(list)
        for rp in self.d["role_packs"]:
            for kid in rp["knowledge_bases"]:
                used[kid].append(rp["name"])
        return [{**kb, "role_packs": used[kb["id"]]} for kb in self.d["knowledge_bases"]]

    def kb_documents(self, kb_id: str) -> list[dict]:
        self._find(self.d["knowledge_bases"], kb_id, "知识库")
        return self.d["kb_documents"][kb_id]

    # ---- 审计 ----
    def traces(self, member_id=None, outcome=None, dept=None, q=None) -> list[dict]:
        out = []
        for t in self.d["traces"]:
            if member_id and t["member_id"] != member_id:
                continue
            if outcome and t["outcome"] != outcome:
                continue
            if dept and t["dept"] != dept:
                continue
            if q and q not in t["member"] and q not in t["summary"]:
                continue
            out.append({k: v for k, v in t.items() if k != "steps"} | {"step_count": len(t["steps"])})
        return out

    def trace(self, trace_id: str) -> dict:
        return self._find(self.d["traces"], trace_id, "链路")

    # ---- 用量 ----
    def usage(self, days: int = 30) -> dict:
        d = self.d
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        rows = [u for u in d["usage_daily"] if u["date"] >= since]
        model_names = {m["id"]: m["name"] for m in d["models"]}
        model_loc = {m["id"]: m["location"] for m in d["models"]}

        daily = defaultdict(lambda: defaultdict(float))
        by_dept = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        by_model = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        for u in rows:
            dn = d["dept_names"][u["dept"]]
            daily[u["date"]][dn] += u["cost"]
            by_dept[dn]["tokens"] += u["tokens"]
            by_dept[dn]["cost"] += u["cost"]
            by_model[u["model"]]["tokens"] += u["tokens"]
            by_model[u["model"]]["cost"] += u["cost"]

        # 部门顺序跟随组织架构；用量里出现但组织里没有的部门（如未分配）排在最后
        dept_order = [dep["name"] for dep in d["departments"]]
        dept_order += sorted({dn for dn in by_dept if dn not in dept_order})
        quota = {}
        for dep in d["departments"]:
            rp = self._find(d["role_packs"], dep["role_pack"], "岗位包")
            quota[dep["name"]] = rp["monthly_quota"] * dep["member_count"]

        return {
            "days": days,
            "total_tokens": sum(u["tokens"] for u in rows),
            "total_cost": round(sum(u["cost"] for u in rows), 2),
            "local_ratio": round(sum(u["tokens"] for u in rows if u["model"] == "qwen-local") /
                                 max(1, sum(u["tokens"] for u in rows)), 3),
            "departments": dept_order,
            "daily": [{"date": k, **{dn: round(v.get(dn, 0), 2) for dn in dept_order}} for k, v in sorted(daily.items())],
            "by_dept": [{"dept": dn, "tokens": by_dept[dn]["tokens"], "cost": round(by_dept[dn]["cost"], 2),
                         "quota": quota.get(dn, 0)} for dn in dept_order],
            "by_model": [{"model": model_names[k], "location": model_loc[k], "tokens": v["tokens"],
                          "cost": round(v["cost"], 2)} for k, v in by_model.items()],
            "top_members": d["member_usage"][:10],
        }
