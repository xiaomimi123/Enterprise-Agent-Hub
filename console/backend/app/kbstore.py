"""知识库文档：Markdown 存在数据库里，带版本，在控制台查看和编辑；发布后同步到 RAGFlow 检索索引。

- 首次启动把 vault/<知识库名>/**/*.md 导入为第 1 版（已有的不覆盖）；之后以数据库为准，vault/ 目录只是初始数据。
- 谁能怎么改（plan_for，规则同技能库）：管理员、老板改任何知识库直接生效；部门主管改本部门的知识库直接生效，
  改「全公司」知识库要提交审核（老板 / 管理员通过后才生效），不能改别的部门的。新建、修改、删除、回滚都走同一套规则。
- 每次保存都是新版本；删除也是一个版本（可以回滚找回）；回滚是用旧内容生成新版本。
- 检索读的永远是「当前生效的版本」。
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path

from . import db, kbmeta
from .config import settings
from .content import DATASET_PREFIX, KB_REGISTRY
from .skillstore import ALL, DIRECT, REVIEW, Conflict, SkillError, can_review, plan_for

log = logging.getLogger("hub.kb")

MAX_BYTES = 256 * 1024
NAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
EXTENSION = ".md"


class KbError(SkillError):
    """参数不合法或没有权限，消息可以直接给用户看。"""


@contextmanager
def _tx():
    with db.connect() as conn, conn.transaction():
        yield conn


def clean_name(name: str) -> str:
    name = (name or "").strip()
    if name.lower().endswith(EXTENSION):
        name = name[: -len(EXTENSION)].strip()
    if not name or len(name) > 60 or NAME_BAD.search(name) or name.startswith("."):
        raise KbError("文档名 1–60 个字，不能含 \\ / : * ? \" < > | 等符号，也不能以点开头。")
    return name


def clean_content(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").lstrip("﻿")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise KbError(f"文档内容不能超过 {MAX_BYTES // 1024} KB。")
    if not text.strip():
        raise KbError("文档内容不能为空。")
    return text if text.endswith("\n") else text + "\n"


def kb_dept(kb_id: str) -> str:
    kbmeta.refresh()
    if kb_id not in KB_REGISTRY:
        raise KbError("知识库不存在。")
    return KB_REGISTRY[kb_id]["dept"]


# ---- 导入 ----

def import_from_disk() -> int:
    """把 vault/ 里数据库还没有的文档导入为第 1 版。同一知识库里重名（不同子文件夹）的只导入第一个。"""
    n = 0
    root = Path(settings.vault_dir)
    have = {(r["kb_id"], r["name"]) for r in _all_docs()}
    for kb_id, meta in KB_REGISTRY.items():
        folder = root / meta["name"]
        if not folder.is_dir():
            continue
        for p in sorted(folder.rglob("*.md")):
            key = (kb_id, p.stem)
            if key in have or NAME_BAD.search(p.stem):
                continue
            text = p.read_text(encoding="utf-8").replace("\r\n", "\n")
            if not text.strip():
                continue
            with _tx() as conn:
                conn.execute("INSERT INTO kb_docs (kb_id, name, published_version, synced_version) VALUES (%s, %s, 1, 1)", key)  # vault 里的文档此前已经同步过
                conn.execute("INSERT INTO kb_doc_versions (kb_id, name, version, content, author, author_name, note, status) "
                             "VALUES (%s, %s, 1, %s, 'system', '系统导入', '从 vault/ 目录导入', 'published')", (*key, text))
            have.add(key)
            n += 1
    return n


# ---- 读 ----

def _all_docs() -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM kb_docs").fetchall()


def list_docs(kb_id: str) -> list[dict]:
    """知识库里当前生效的文档（含待审核数、字数），按名称排序。"""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT d.name, d.published_version, d.synced_version, d.updated_at, v.content, v.author_name, "
            "(SELECT count(*) FROM kb_doc_versions p WHERE p.kb_id = d.kb_id AND p.name = d.name AND p.status = 'pending') AS pending "
            "FROM kb_docs d LEFT JOIN kb_doc_versions v ON v.kb_id = d.kb_id AND v.name = d.name AND v.version = d.published_version "
            "WHERE d.kb_id = %s AND NOT d.deleted AND d.published_version > 0 ORDER BY d.name", (kb_id,)).fetchall()
    return rows


def published_docs(kb_ids: list[str] | None = None) -> list[dict]:
    """检索用：{kb_id, name, content}。"""
    with db.connect() as conn:
        rows = conn.execute("SELECT d.kb_id, d.name, v.content FROM kb_docs d JOIN kb_doc_versions v ON v.kb_id = d.kb_id AND v.name = d.name "
                            "AND v.version = d.published_version WHERE NOT d.deleted AND d.published_version > 0").fetchall()
    return [r for r in rows if kb_ids is None or r["kb_id"] in kb_ids]


def get_doc(kb_id: str, name: str) -> dict | None:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM kb_docs WHERE kb_id = %s AND name = %s", (kb_id, name)).fetchone()


def versions(kb_id: str, name: str, limit: int = 30) -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT * FROM kb_doc_versions WHERE kb_id = %s AND name = %s ORDER BY version DESC LIMIT %s", (kb_id, name, limit)).fetchall()


def pending(scope: dict, user_name: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT v.*, d.published_version FROM kb_doc_versions v JOIN kb_docs d ON d.kb_id = v.kb_id AND d.name = v.name "
                            "WHERE v.status = 'pending' ORDER BY v.created_at").fetchall()
    return rows if can_review(scope) else [r for r in rows if r["author"] == user_name]


# ---- 写 ----

def _next_version(conn, kb_id: str, name: str) -> int:
    return conn.execute("SELECT coalesce(max(version), 0) + 1 AS n FROM kb_doc_versions WHERE kb_id = %s AND name = %s", (kb_id, name)).fetchone()["n"]


def _publish(conn, kb_id: str, name: str, version: int, is_delete: bool) -> None:
    conn.execute("UPDATE kb_docs SET published_version = %s, deleted = %s, updated_at = now() WHERE kb_id = %s AND name = %s", (version, is_delete, kb_id, name))
    conn.execute("UPDATE kb_doc_versions SET status = 'published' WHERE kb_id = %s AND name = %s AND version = %s", (kb_id, name, version))


def _submit(kb_id: str, name: str, scope: dict, user: dict, text: str | None, note: str, base_version: int | None, delete: bool = False,
            creating: bool = False) -> dict:
    mode = plan_for(scope, kb_dept(kb_id))
    if mode is None:
        raise KbError("你没有修改这个知识库的权限：部门主管只能改本部门的知识库（和提交全公司知识库的修改）。")
    body = "" if delete else clean_content(text or "")
    with _tx() as conn:
        cur = conn.execute("SELECT published_version, deleted FROM kb_docs WHERE kb_id = %s AND name = %s FOR UPDATE", (kb_id, name)).fetchone()
        if creating:
            if cur is not None and not cur["deleted"]:
                raise KbError(f"文档「{name}」已经存在。")
            if cur is None:
                conn.execute("INSERT INTO kb_docs (kb_id, name, published_version) VALUES (%s, %s, 0)", (kb_id, name))
                cur = {"published_version": 0, "deleted": False}
        elif cur is None or cur["deleted"]:
            raise KbError("文档不存在。")
        if base_version is not None and base_version != cur["published_version"]:
            raise Conflict(f"这篇文档已经被更新到第 {cur['published_version']} 版（你是基于第 {base_version} 版修改的），请刷新后在最新内容上重新修改。")
        if mode == DIRECT and not delete and not creating:
            last = conn.execute("SELECT content FROM kb_doc_versions WHERE kb_id = %s AND name = %s AND version = %s", (kb_id, name, cur["published_version"])).fetchone()
            if last and last["content"] == body:
                raise KbError("内容没有变化。")
        if mode == REVIEW:
            other = conn.execute("SELECT author, version FROM kb_doc_versions WHERE kb_id = %s AND name = %s AND status = 'pending'", (kb_id, name)).fetchone()
            if other and other["author"] != user["name"]:
                raise KbError("这篇文档已经有一份待审核的修改，请等审核完成后再提交。")
            if other:
                conn.execute("UPDATE kb_doc_versions SET status = 'rejected', review_note = '被新的提交取代' WHERE kb_id = %s AND name = %s AND version = %s", (kb_id, name, other["version"]))
        v = _next_version(conn, kb_id, name)
        if delete:  # 删除这一版保留上一版的内容，回滚时才找得回
            prev = conn.execute("SELECT content FROM kb_doc_versions WHERE kb_id = %s AND name = %s AND version = %s", (kb_id, name, cur["published_version"])).fetchone()
            body = prev["content"] if prev else ""
        conn.execute("INSERT INTO kb_doc_versions (kb_id, name, version, content, is_delete, author, author_name, note, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (kb_id, name, v, body, delete, user["name"], user.get("display_name") or user["name"], (note or "").strip()[:200], "published" if mode == DIRECT else "pending"))
        if mode == DIRECT:
            _publish(conn, kb_id, name, v, delete)
    return {"version": v, "status": "published" if mode == DIRECT else "pending", "published": mode == DIRECT}


def create(kb_id: str, name: str, scope: dict, user: dict, text: str, note: str = "") -> dict:
    return _submit(kb_id, clean_name(name), scope, user, text, note or "新建", None, creating=True)


def save(kb_id: str, name: str, scope: dict, user: dict, text: str, note: str = "", base_version: int | None = None) -> dict:
    return _submit(kb_id, name, scope, user, text, note, base_version)


def delete(kb_id: str, name: str, scope: dict, user: dict, note: str = "") -> dict:
    return _submit(kb_id, name, scope, user, None, note or "删除", None, delete=True)


def rollback(kb_id: str, name: str, scope: dict, user: dict, version: int, note: str = "") -> dict:
    """用旧版本的内容生成新版本（文档被删除后也可以回滚找回）。"""
    old = next((v for v in versions(kb_id, name, 1000) if v["version"] == version and v["status"] == "published" and not v["is_delete"]), None)
    if old is None:
        raise KbError(f"第 {version} 版不存在，或从未发布过。")
    doc = get_doc(kb_id, name)
    if doc is None:
        raise KbError("文档不存在。")
    if doc["deleted"]:  # 找回已删除的文档：当作新建
        return _submit(kb_id, name, scope, user, old["content"], note or f"回滚到第 {version} 版（找回）", None, creating=True)
    return _submit(kb_id, name, scope, user, old["content"], note or f"回滚到第 {version} 版", None)


def review(kb_id: str, name: str, version: int, scope: dict, user: dict, approve: bool, note: str = "") -> dict:
    if not can_review(scope):
        raise KbError("只有老板和管理员可以审核。")
    with _tx() as conn:
        v = conn.execute("SELECT * FROM kb_doc_versions WHERE kb_id = %s AND name = %s AND version = %s AND status = 'pending' FOR UPDATE", (kb_id, name, version)).fetchone()
        if v is None:
            raise KbError("没有找到这份待审核的修改（可能已经被处理）。")
        if approve:
            _publish(conn, kb_id, name, version, v["is_delete"])
        conn.execute("UPDATE kb_doc_versions SET status = %s, reviewer = %s, review_note = %s, reviewed_at = now() WHERE kb_id = %s AND name = %s AND version = %s",
                     ("published" if approve else "rejected", user["name"], (note or "").strip()[:200], kb_id, name, version))
    return {"version": version, "status": "published" if approve else "rejected", "published": approve}


# ---- 同步到检索索引（RAGFlow） ----

def sync_doc(client, kb_id: str, name: str) -> bool:
    """把一篇文档的当前版本同步到 RAGFlow：删掉旧的、上传新的、触发解析；已删除的只删旧的。失败返回 False，之后可重试。"""
    doc = get_doc(kb_id, name)
    if doc is None:
        return True
    try:
        ds = client.ensure_dataset(f"{DATASET_PREFIX}{kb_id}", KB_REGISTRY[kb_id]["name"], settings.ragflow_embedding_model)
        filename = f"{name}{EXTENSION}"
        old = [d["id"] for d in client.list_documents(ds) if d["name"] == filename]
        if old:
            client.delete_documents(ds, old)
        if not doc["deleted"] and doc["published_version"] > 0:
            text = next((v["content"] for v in versions(kb_id, name, 1000) if v["version"] == doc["published_version"]), "")
            doc_id = client.upload(ds, filename, text.encode("utf-8"))
            client.parse(ds, [doc_id])
        with db.connect() as conn:
            conn.execute("UPDATE kb_docs SET synced_version = %s WHERE kb_id = %s AND name = %s", (doc["published_version"], kb_id, name))
        return True
    except Exception as e:  # noqa: BLE001 索引同步失败不影响文档本身已保存
        log.warning("知识库文档同步到 RAGFlow 失败 %s/%s：%s", kb_id, name, e)
        return False


def unsynced(kb_id: str | None = None) -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT kb_id, name FROM kb_docs WHERE synced_version <> published_version AND published_version > 0"
                            + (" AND kb_id = %s" if kb_id else ""), (kb_id,) if kb_id else ()).fetchall()


def ui_documents(kb_id: str) -> list[dict]:
    """控制台文档列表：名称、版本、片段数、索引状态（读 RAGFlow 的真实解析状态，没配置就当作已索引）。"""
    from .content import RUN_STATUS
    from .ragflow import from_settings
    remote: dict[str, dict] = {}
    client = from_settings()
    if client is not None:
        try:
            ds = client.find_dataset(f"{DATASET_PREFIX}{kb_id}")
            remote = {d["name"]: d for d in client.list_documents(ds)} if ds else {}
        except Exception as e:  # noqa: BLE001
            log.warning("读取 RAGFlow 文档状态失败：%s", e)
    out = []
    for d in list_docs(kb_id):
        r = remote.get(f"{d['name']}{EXTENSION}")
        if d["synced_version"] != d["published_version"]:
            status = "待同步"
        elif r:
            status = RUN_STATUS.get(r.get("run"), r.get("run") or "未知")
        else:
            status = "已索引" if client is None else "未索引"
        out.append({"id": d["name"], "title": d["name"], "type": "md", "version": d["published_version"], "pending": d["pending"],
                    "author_name": d["author_name"] or "", "chunks": len([b for b in re.split(r"\n\s*\n", d["content"] or "") if b.strip()]),
                    "chars": len(d["content"] or ""), "status": status, "updated_at": d["updated_at"].isoformat()})
    return out
