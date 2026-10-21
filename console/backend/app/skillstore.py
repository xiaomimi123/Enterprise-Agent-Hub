"""技能库：技能（SKILL.md）存在数据库里，带版本，在控制台编辑。

- 首次启动把 skills/<部门>/<id>/SKILL.md 导入为第 1 版（已有的不覆盖）；之后以数据库为准，skills/ 目录只是初始数据。
- 谁能怎么改（plan_for）：管理员、老板改任何技能都直接生效；部门主管改本部门技能直接生效，改「全公司」技能要提交审核（老板 / 管理员通过后才生效），
  不能改其他部门的技能。
- 每次保存都是新版本；回滚是用旧内容生成一个新版本（历史是一条直线，永远不丢）；新版本基于旧版本时要带 base_version，
  被别人先改了就拒绝，避免互相覆盖。
- 员工的 agent 读到的永远是 published_version 那一版。
"""

from __future__ import annotations

import re
from contextlib import contextmanager

from . import content as disk
from . import db, roles
from .config import settings

ALL = "all"
MAX_BYTES = 64 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
DIRECT, REVIEW = "direct", "review"


@contextmanager
def _tx():
    """一个事务：db.connect() 是自动提交的，改多张表 / 需要行锁的地方必须包在事务里。"""
    with db.connect() as conn, conn.transaction():
        yield conn


class SkillError(ValueError):
    """参数不合法或没有权限，消息可以直接给用户看。"""


class Conflict(SkillError):
    pass


def plan_for(scope: dict, skill_dept: str) -> str | None:
    """这个角色改这个部门的技能：direct（直接生效）、review（提交审核）、None（不能改）。"""
    if scope["role"] in (roles.ADMIN, roles.BOSS):
        return DIRECT
    if scope["role"] == roles.MANAGER:
        if skill_dept in (scope["depts"] or []):
            return DIRECT
        if skill_dept == ALL:
            return REVIEW
    return None


def can_review(scope: dict) -> bool:
    return scope["role"] in (roles.ADMIN, roles.BOSS)


def clean_content(text: str) -> tuple[str, dict]:
    """规范化并校验 SKILL.md：必须有 frontmatter，且包含 name 和 description。返回 (内容, frontmatter)。"""
    text = (text or "").replace("\r\n", "\n").lstrip("﻿")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SkillError(f"技能内容不能超过 {MAX_BYTES // 1024} KB。")
    meta, body = disk._frontmatter(text)
    if not meta.get("name") or not meta.get("description"):
        raise SkillError("技能开头要有 frontmatter（--- 包起来的部分），并写上 name（名称）和 description（一句话说明）。")
    if not body.strip():
        raise SkillError("技能正文不能为空。")
    return text if text.endswith("\n") else text + "\n", meta


# ---- 读 ----

def _disk_skills(dept_ids: dict[str, str]) -> list[dict]:
    """skills/ 目录里的技能。dept_ids：部门显示名 → 部门 id；对不上的部门保留原名（只有管理员和老板能改）。"""
    out = []
    for s in disk.list_skills():
        name = s["dept_name"]
        out.append({**s, "dept": ALL if name == "全公司" else dept_ids.get(name, name), "text": disk.read_skill(s["id"]) or ""})
    return out


def import_from_disk(dept_ids: dict[str, str]) -> int:
    """把 skills/ 里数据库还没有的技能导入为第 1 版。返回导入个数。"""
    have = {r["id"] for r in _rows()}
    n = 0
    for s in _disk_skills(dept_ids):
        if s["id"] in have or not s["text"].strip():
            continue
        try:
            text, meta = clean_content(s["text"])
        except SkillError:
            continue  # 格式不合规的旧文件不导入，仍然可以通过磁盘兜底读到
        with _tx() as conn:
            conn.execute("INSERT INTO skills (id, dept_id, name, description, published_version) VALUES (%s, %s, %s, %s, 1)",
                         (s["id"], s["dept"], meta["name"], meta["description"]))
            conn.execute("INSERT INTO skill_versions (skill_id, version, content, author, author_name, note, status) "
                         "VALUES (%s, 1, %s, 'system', '系统导入', '从 skills/ 目录导入', 'published')", (s["id"], text))
        n += 1
    return n


def _rows() -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM skills ORDER BY dept_id, id").fetchall()


def list_skills() -> list[dict]:
    """已发布的技能（数据库优先，磁盘上还没导入的作兜底）：id、name、description、dept、version、updated_at。"""
    rows = {r["id"]: r for r in _rows()} if settings.database_url else {}
    out = [{"id": r["id"], "name": r["name"], "description": r["description"], "dept": r["dept_id"], "version": r["published_version"],
            "updated_at": r["updated_at"].isoformat()} for r in rows.values() if r["published_version"] > 0]
    for s in disk.list_skills():
        if s["id"] not in rows:
            out.append({"id": s["id"], "name": s["name"], "description": s["description"], "dept": ALL if s["dept_name"] == "全公司" else s["dept_name"],
                        "version": 0, "updated_at": s["updated_at"]})
    return out


def read_skill(skill_id: str) -> str | None:
    """员工的 agent 读到的内容：当前已发布的版本。"""
    if settings.database_url:
        with db.connect() as conn:
            row = conn.execute("SELECT v.content FROM skills s JOIN skill_versions v ON v.skill_id = s.id AND v.version = s.published_version "
                               "WHERE s.id = %s AND s.published_version > 0", (skill_id,)).fetchone()
            if row:
                return row["content"]
            if conn.execute("SELECT 1 FROM skills WHERE id = %s", (skill_id,)).fetchone():
                return None  # 在库里但还没有已发布的版本（等审核）：不回退到磁盘旧文件
    return disk.read_skill(skill_id)


def published_meta() -> dict[str, dict]:
    """每个技能当前版本的作者，以及有没有待审核的修改：{id: {author_name, pending}}。"""
    with db.connect() as conn:
        rows = conn.execute("SELECT s.id, v.author_name, (SELECT count(*) FROM skill_versions p WHERE p.skill_id = s.id AND p.status = 'pending') AS pending "
                            "FROM skills s LEFT JOIN skill_versions v ON v.skill_id = s.id AND v.version = s.published_version").fetchall()
    return {r["id"]: {"author_name": r["author_name"] or "", "pending": r["pending"]} for r in rows}


def get_skill(skill_id: str) -> dict | None:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM skills WHERE id = %s", (skill_id,)).fetchone()


def versions(skill_id: str, limit: int = 30) -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM skill_versions WHERE skill_id = %s ORDER BY version DESC LIMIT %s", (skill_id, limit)).fetchall()


def pending(scope: dict, user_name: str) -> list[dict]:
    """待审核的修改：老板 / 管理员看全部，主管只看自己提交的。"""
    with db.connect() as conn:
        rows = conn.execute("SELECT v.*, s.dept_id, s.name AS skill_name, s.published_version FROM skill_versions v JOIN skills s ON s.id = v.skill_id "
                            "WHERE v.status = 'pending' ORDER BY v.created_at").fetchall()
    return rows if can_review(scope) else [r for r in rows if r["author"] == user_name]


# ---- 写 ----

def _next_version(conn, skill_id: str) -> int:
    return conn.execute("SELECT coalesce(max(version), 0) + 1 AS n FROM skill_versions WHERE skill_id = %s", (skill_id,)).fetchone()["n"]


def _publish(conn, skill_id: str, version: int, meta: dict) -> None:
    conn.execute("UPDATE skills SET published_version = %s, name = %s, description = %s, updated_at = now() WHERE id = %s",
                 (version, meta["name"], meta["description"], skill_id))
    conn.execute("UPDATE skill_versions SET status = 'published' WHERE skill_id = %s AND version = %s", (skill_id, version))


def _submit(skill_id: str, scope: dict, user: dict, text: str, note: str, base_version: int | None, dept: str) -> dict:
    mode = plan_for(scope, dept)
    if mode is None:
        raise SkillError("你没有修改这个技能的权限：部门主管只能改本部门的技能（和提交全公司技能的修改）。")
    text, meta = clean_content(text)
    with _tx() as conn:
        cur = conn.execute("SELECT published_version FROM skills WHERE id = %s FOR UPDATE", (skill_id,)).fetchone()
        if cur is None:
            raise SkillError("技能不存在。")
        if base_version is not None and base_version != cur["published_version"]:
            raise Conflict(f"这个技能已经被更新到第 {cur['published_version']} 版（你是基于第 {base_version} 版修改的），请刷新后在最新内容上重新修改。")
        last = conn.execute("SELECT content FROM skill_versions WHERE skill_id = %s AND version = %s", (skill_id, cur["published_version"])).fetchone()
        if last and last["content"] == text and mode == DIRECT:
            raise SkillError("内容没有变化。")
        if mode == REVIEW:
            other = conn.execute("SELECT author, version FROM skill_versions WHERE skill_id = %s AND status = 'pending'", (skill_id,)).fetchone()
            if other and other["author"] != user["name"]:
                raise SkillError("这个技能已经有一份待审核的修改，请等审核完成后再提交。")
            if other:  # 自己重新提交：取代上一份待审核的
                conn.execute("UPDATE skill_versions SET status = 'rejected', review_note = '被新的提交取代' WHERE skill_id = %s AND version = %s",
                             (skill_id, other["version"]))
        v = _next_version(conn, skill_id)
        conn.execute("INSERT INTO skill_versions (skill_id, version, content, author, author_name, note, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (skill_id, v, text, user["name"], user.get("display_name") or user["name"], (note or "").strip()[:200],
                      "published" if mode == DIRECT else "pending"))
        if mode == DIRECT:
            _publish(conn, skill_id, v, meta)
    return {"version": v, "status": "published" if mode == DIRECT else "pending"}


def save(skill_id: str, scope: dict, user: dict, text: str, note: str = "", base_version: int | None = None) -> dict:
    row = get_skill(skill_id)
    if row is None:
        raise SkillError("技能不存在。")
    return _submit(skill_id, scope, user, text, note, base_version, row["dept_id"])


def rollback(skill_id: str, scope: dict, user: dict, version: int, note: str = "") -> dict:
    """用旧版本的内容生成一个新版本（权限规则同修改）。"""
    row = get_skill(skill_id)
    if row is None:
        raise SkillError("技能不存在。")
    old = next((v for v in versions(skill_id, 1000) if v["version"] == version and v["status"] == "published"), None)
    if old is None:
        raise SkillError(f"第 {version} 版不存在，或从未发布过。")
    return _submit(skill_id, scope, user, old["content"], note or f"回滚到第 {version} 版", None, row["dept_id"])


def create(skill_id: str, dept: str, scope: dict, user: dict, text: str, note: str = "", valid_depts: set[str] | None = None) -> dict:
    if not ID_RE.match(skill_id or ""):
        raise SkillError("技能 id 只能用小写字母、数字和短横线（2–41 位），如 xhs-topic。")
    if dept != ALL and valid_depts is not None and dept not in valid_depts:
        raise SkillError("部门不存在。")
    mode = plan_for(scope, dept)
    if mode is None:
        raise SkillError("你没有在这个部门新建技能的权限。")
    if get_skill(skill_id) or disk.read_skill(skill_id) is not None:
        raise SkillError(f"技能 id「{skill_id}」已经存在。")
    text, meta = clean_content(text)
    with _tx() as conn:
        conn.execute("INSERT INTO skills (id, dept_id, name, description, published_version) VALUES (%s, %s, %s, %s, 0)",
                     (skill_id, dept, meta["name"], meta["description"]))
        conn.execute("INSERT INTO skill_versions (skill_id, version, content, author, author_name, note, status) VALUES (%s, 1, %s, %s, %s, %s, %s)",
                     (skill_id, text, user["name"], user.get("display_name") or user["name"], (note or "新建").strip()[:200],
                      "published" if mode == DIRECT else "pending"))
        if mode == DIRECT:
            _publish(conn, skill_id, 1, meta)
    return {"version": 1, "status": "published" if mode == DIRECT else "pending"}


def review(skill_id: str, version: int, scope: dict, user: dict, approve: bool, note: str = "") -> dict:
    if not can_review(scope):
        raise SkillError("只有老板和管理员可以审核。")
    with _tx() as conn:
        v = conn.execute("SELECT * FROM skill_versions WHERE skill_id = %s AND version = %s AND status = 'pending' FOR UPDATE", (skill_id, version)).fetchone()
        if v is None:
            raise SkillError("没有找到这份待审核的修改（可能已经被处理）。")
        if approve:
            _, meta = clean_content(v["content"])
            _publish(conn, skill_id, version, meta)
        conn.execute("UPDATE skill_versions SET status = %s, reviewer = %s, review_note = %s, reviewed_at = now() WHERE skill_id = %s AND version = %s",
                     ("published" if approve else "rejected", user["name"], (note or "").strip()[:200], skill_id, version))
    return {"version": version, "status": "published" if approve else "rejected"}
