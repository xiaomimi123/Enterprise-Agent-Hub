"""岗位 / 个人工作成果：上报（report_work）与汇总（控制台看板、老板 agent 的 team_report）。

两类数据合在一起：
- 上报的成果（work_items）：标题、类型、状态、进度、产物链接——回答「做成了什么」；
- 自动统计的活动（审计、GPU 任务）：调用次数、出图出视频数、活跃天数——回答「在不在做」。
主指标是成果；活动只作参考，不能当绩效（调用次数可以被刷）。
汇总是纯函数 build_report，不连库，便于测试。
"""

from __future__ import annotations

import logging

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import db, policy
from .logutil import warn_throttled

log = logging.getLogger("hub.work")

STATUSES = ("进行中", "待审核", "已完成", "受阻")
MAX_TITLE, MAX_KIND, MAX_NOTE, MAX_LINK = 120, 20, 300, 300


class BadReport(ValueError):
    pass


def _clean(report: dict) -> dict:
    title = str(report.get("title") or "").strip()
    if not title:
        raise BadReport("标题不能为空。")
    status = str(report.get("status") or "已完成")
    if status not in STATUSES:
        raise BadReport(f"状态只能是：{'、'.join(STATUSES)}。")
    progress = report.get("progress")
    if progress is None:
        progress = 100 if status == "已完成" else 0
    try:
        progress = max(0, min(100, int(progress)))
    except (TypeError, ValueError):
        raise BadReport("进度要是 0–100 的整数。") from None
    if status == "已完成":
        progress = 100
    link = str(report.get("link") or "").strip()
    if link and not link.startswith(("http://", "https://")):
        raise BadReport("产物链接必须是 http(s) 地址（不要放本机文件路径）。")
    return {"title": title[:MAX_TITLE], "kind": (str(report.get("kind") or "其他").strip() or "其他")[:MAX_KIND],
            "status": status, "progress": progress, "link": link[:MAX_LINK], "note": str(report.get("note") or "").strip()[:MAX_NOTE]}


MAX_KEY = 80
MAX_BATCH = 50


def report_work(p: policy.Principal, trace_id: str, report: dict, item_id: int | None = None, source: str = "agent") -> dict:
    """上报或更新一条成果。更新只能改自己的条目；带 key（应用自动上报）时按 key 幂等写入。"""
    clean = _clean(report)
    key = str(report.get("key") or "").strip()[:MAX_KEY]
    if key and item_id is None:
        new_id = db.upsert_work_item({**clean, "org": p.org, "user_name": p.user_name, "display_name": p.display_name,
                                      "dept": p.dept, "source": source[:40], "trace_id": trace_id, "ext_key": key})
    elif item_id is not None:
        if not db.update_work_item(item_id, p.org, p.user_name, {**clean, "trace_id": trace_id}):
            raise BadReport(f"没有找到你的工作条目 {item_id}。")
        new_id = item_id
    else:
        new_id = db.add_work_item({**clean, "org": p.org, "user_name": p.user_name, "display_name": p.display_name,
                                   "dept": p.dept, "source": source[:40], "trace_id": trace_id})
    db.add_audit(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
                 channel=p.channel, kind="工作", tool="work.report",
                 detail=f"[{clean['kind']}] {clean['title']}（{clean['status']} {clean['progress']}%）", result="通过")
    return {"item_id": new_id, **clean}


def report_batch(p: policy.Principal, trace_id: str, source: str, items: list) -> dict:
    """应用自动上报：逐条校验，坏的跳过并说明原因，好的幂等写入。"""
    accepted, rejected = 0, []
    for i, it in enumerate(items[:MAX_BATCH]):
        try:
            if not isinstance(it, dict) or not str(it.get("key") or "").strip():
                raise BadReport("自动上报的每一条都要有 key。")
            report_work(p, trace_id, it, source=source)
            accepted += 1
        except BadReport as e:
            rejected.append({"index": i, "reason": str(e)})
    rejected += [{"index": i, "reason": f"一次最多 {MAX_BATCH} 条"} for i in range(MAX_BATCH, len(items))]
    return {"accepted": accepted, "rejected": rejected}


def period_start(days: int, now: datetime | None = None) -> datetime:
    """从「今天 0 点」往前数 days 天（days=1 就是今天）。"""
    now = now or datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=max(1, days) - 1)


def _blank_items() -> dict:
    return {s: 0 for s in STATUSES} | {"total": 0}


def _is_image(w: str) -> bool:
    return "video" not in w


def build_report(*, days: int, events: list[dict], items: list[dict], tasks: list[dict], assignments: dict[str, str],
                 packs: dict[str, dict], members: list[dict] | None = None, now: datetime | None = None,
                 person: str | None = None, depts: list[str] | None = None, dept_defaults: dict[str, str] | None = None) -> dict:
    """depts 不为 None 时只汇总这些部门的人（部门主管的视角）。"""
    now = now or datetime.now().astimezone()
    since = period_start(days, now)
    people: dict[str, dict] = {}

    def who(user_name: str, display: str = "", dept: str = "") -> dict:
        pack_id = assignments.get(user_name) or policy.default_pack_id(dept, dept_defaults)
        pack = packs.get(pack_id) or packs.get(policy.FALLBACK_ROLE_PACK) or {"name": "未分配"}
        pr = people.setdefault(user_name, {
            "user_name": user_name, "display_name": display or user_name, "dept": dept, "role": pack["name"],
            "items": _blank_items(), "kinds": Counter(), "images": 0, "videos": 0, "calls": 0, "denied": 0,
            "days": set(), "last_active": None})
        if display and pr["display_name"] == user_name:
            pr["display_name"] = display
        return pr

    for m in members or []:
        if not (m.get("user_name") or m.get("id")):
            continue
        who(m.get("user_name") or m.get("id") or "", m.get("name", ""), m.get("dept", ""))
    for e in events:
        if e["ts"] < since or e["tool"] == "work.report":
            continue
        pr = who(e["user_name"], e.get("display_name", ""), e.get("dept", ""))
        pr["calls"] += 1
        pr["denied"] += e["result"] == "拒绝"
        pr["days"].add(e["ts"].astimezone().date())
        pr["last_active"] = max(filter(None, [pr["last_active"], e["ts"]]))
    for t in tasks:
        if t["status"] != "done" or (t.get("finished_at") or t["created_at"]) < since:
            continue
        pr = who(t["user_name"], t.get("display_name", ""), t.get("dept", ""))
        n = max(1, len(t.get("images") or []))
        if _is_image(t["workflow"]):
            pr["images"] += n
        else:
            pr["videos"] += 1
    for it in items:
        if it["updated_at"] < since:
            continue
        pr = who(it["user_name"], it.get("display_name", ""), it.get("dept", ""))
        pr["items"][it["status"]] += 1
        pr["items"]["total"] += 1
        pr["kinds"][it["kind"]] += 1

    rows = [pr for u, pr in people.items() if (not person or u == person or pr["display_name"] == person)
            and (depts is None or pr["dept"] in depts)]
    for pr in rows:
        pr["active_days"] = len(pr.pop("days"))
        pr["kinds"] = dict(pr["kinds"])
        pr["active"] = bool(pr["calls"] or pr["items"]["total"] or pr["images"] or pr["videos"])
    rows.sort(key=lambda r: (-r["items"]["已完成"], -r["items"]["total"], -r["calls"], r["user_name"]))

    roles: dict[str, dict] = defaultdict(lambda: {"people": 0, "active_people": 0, "items": _blank_items(), "kinds": Counter(),
                                                  "images": 0, "videos": 0, "calls": 0})
    for pr in rows:
        r = roles[pr["role"]]
        r["people"] += 1
        r["active_people"] += pr["active"]
        for s in (*STATUSES, "total"):
            r["items"][s] += pr["items"][s]
        r["kinds"].update(pr["kinds"])
        for k in ("images", "videos", "calls"):
            r[k] += pr[k]
    role_rows = [{"role": name, **{**r, "kinds": dict(r["kinds"])}} for name, r in roles.items()]
    role_rows.sort(key=lambda r: (-r["items"]["已完成"], -r["calls"], r["role"]))

    keep = {r["user_name"] for r in rows}
    recent = [{"id": i["id"], "user_name": i["user_name"], "display_name": i.get("display_name") or i["user_name"],
               "role": people[i["user_name"]]["role"] if i["user_name"] in people else "", "kind": i["kind"], "title": i["title"],
               "status": i["status"], "progress": i["progress"], "link": i["link"], "note": i["note"], "source": i["source"],
               "updated_at": i["updated_at"].isoformat()}
              for i in items if i["updated_at"] >= since and i["user_name"] in keep][:60]
    totals = {"people": len(rows), "active_people": sum(r["active"] for r in rows), "items": _blank_items(),
              "images": sum(r["images"] for r in rows), "videos": sum(r["videos"] for r in rows),
              "calls": sum(r["calls"] for r in rows), "denied": sum(r["denied"] for r in rows)}
    for r in rows:
        for s in (*STATUSES, "total"):
            totals["items"][s] += r["items"][s]
    for r in rows:
        r["last_active"] = r["last_active"].isoformat() if r["last_active"] else None
    return {"days": days, "since": since.isoformat(), "generated_at": now.isoformat(), "totals": totals,
            "roles": role_rows, "people": rows, "items": recent,
            "inactive": [r["display_name"] for r in rows if not r["active"]],
            "blocked": [i for i in recent if i["status"] == "受阻"],
            "digest": digest(days, totals, role_rows, [r["display_name"] for r in rows if not r["active"]], recent)}


def digest(days: int, totals: dict, roles: list[dict], inactive: list[str], recent: list[dict]) -> str:
    """给 agent 写日报的事实摘要：只陈述数据，不下判断。"""
    it = totals["items"]
    span = "今天" if days == 1 else f"近 {days} 天"
    lines = [f"{span}：{totals['active_people']}/{totals['people']} 人有活动；上报成果 {it['total']} 项"
             f"（已完成 {it['已完成']}、待审核 {it['待审核']}、进行中 {it['进行中']}、受阻 {it['受阻']}）；"
             f"出图 {totals['images']} 张、出视频 {totals['videos']} 条。"]
    for r in roles:
        if r["items"]["total"] or r["calls"]:
            lines.append(f"- {r['role']}：{r['active_people']}/{r['people']} 人活动，成果 {r['items']['total']} 项（完成 {r['items']['已完成']}）")
    for i in [i for i in recent if i["status"] == "受阻"][:5]:
        lines.append(f"- 受阻：{i['display_name']}「{i['title']}」{('：' + i['note']) if i['note'] else ''}")
    if inactive:
        lines.append(f"- 期间无活动：{'、'.join(inactive[:15])}{'等' if len(inactive) > 15 else ''}")
    if not it["total"]:
        lines.append("- 提示：期间没有人上报成果，以上只反映活动量；成果需要员工的 agent 调用 report_work 上报。")
    return "\n".join(lines)


def kb_overdue(depts: list[str] | None, now: datetime | None = None) -> list[dict]:
    """逾期没有复核的知识库（主管只看自己部门和全公司的）。"""
    from . import kbmeta
    kbmeta.refresh()
    now = now or datetime.now().astimezone()
    out = []
    for kb in kbmeta.overdue(now):
        if depts is not None and kb["dept"] not in (*depts, "all"):
            continue
        left = kbmeta.due_in_days(kb, now)
        out.append({"id": kb["id"], "name": kb["name"], "dept": kb["dept"], "owner": kb["owner"], "overdue_days": -left if left is not None and left < 0 else 0})
    return sorted(out, key=lambda k: -k["overdue_days"])


def _open_proposals(depts: list[str] | None) -> int:
    from . import proposals, roles
    scope = {"role": roles.ADMIN, "depts": None} if depts is None else {"role": roles.MANAGER, "depts": depts}
    try:
        return len(proposals.list_for(scope, "open"))
    except Exception:  # noqa: BLE001 没有这张表（旧库）时不影响日报
        warn_throttled(log, "work.open_proposals", "统计待处理的改进建议失败，日报里按 0 显示")
        return 0


def load_report(org: str, days: int, members: list[dict] | None = None, person: str | None = None, depts: list[str] | None = None) -> dict:
    """从库里取数据并汇总。"""
    days = max(1, min(int(days), 30))
    since = period_start(days)
    r = build_report(days=days, events=db.recent_audit(org, days + 1), items=db.work_items_since(org, since),
                     tasks=db.gpu_tasks_since(org, days + 1), assignments=db.assignments(org),
                     packs={p["id"]: p for p in db.role_packs()}, members=members, person=person, depts=depts, dept_defaults=db.dept_defaults(org))
    r["kb_overdue"] = kb_overdue(depts)
    r["proposals_open"] = _open_proposals(depts)
    if r["proposals_open"]:
        r["digest"] += f"\n- 待处理的改进建议：{r['proposals_open']} 条（控制台「改进建议」页）"
    if r["kb_overdue"]:
        r["digest"] += "\n- 知识库逾期未复核：" + "、".join(f"{k['name']}（{k['overdue_days']} 天）" for k in r["kb_overdue"][:8])
    return r
