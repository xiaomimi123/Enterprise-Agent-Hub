"""技能仓库与知识库的本地实现。

- 技能：skills/<部门>/<技能 id>/SKILL.md（markdown + frontmatter），文件夹名即技能 id
- 知识库：vault/<知识库名>/*.md（Obsidian vault），文件夹名与 demo_seed.KNOWLEDGE_BASES 中的名称对应
- 检索：配置了 RAGFlow（RAGFLOW_ENDPOINT + RAGFLOW_API_KEY）就走 RAGFlow 混合检索；未配置或 RAGFlow 出错时，
  回退到本地 vault 的字符二元组关键词检索（对中文友好、无需分词）。两者返回结构相同
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import demo_seed
from .config import settings
from .ragflow import RagflowError, from_settings

log = logging.getLogger("hub.content")
DATASET_PREFIX = "hub-"

# 知识库注册表：id → 元数据（名称、部门、密级、是否允许外部智能体读取）
KB_REGISTRY = {
    kid: {"id": kid, "name": name, "dept": dept, "classification": level, "source": source, "external_access": external}
    for kid, name, dept, level, source, external in demo_seed.KNOWLEDGE_BASES
}
KB_BY_NAME = {v["name"]: k for k, v in KB_REGISTRY.items()}


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def list_skills() -> list[dict]:
    root = Path(settings.skills_dir)
    out = []
    for p in sorted(root.glob("*/*/SKILL.md")):
        meta, _ = _frontmatter(p.read_text(encoding="utf-8"))
        out.append({
            "id": p.parent.name,
            "name": meta.get("name", p.parent.name),
            "description": meta.get("description", ""),
            "dept_name": meta.get("department", p.parent.parent.name),
            "version": meta.get("version", "1.0.0"),
            "source": str(p.relative_to(root.parent)),
            "updated_at": datetime.fromtimestamp(p.stat().st_mtime).astimezone().replace(microsecond=0).isoformat(),
        })
    return out


def read_skill(skill_id: str) -> str | None:
    for p in Path(settings.skills_dir).glob(f"*/{skill_id}/SKILL.md"):
        return p.read_text(encoding="utf-8")
    return None


@dataclass
class Chunk:
    kb_id: str
    doc: str
    heading: str
    text: str


def _chunks() -> list[Chunk]:
    out = []
    for folder in sorted(Path(settings.vault_dir).iterdir()):
        kb_id = KB_BY_NAME.get(folder.name) if folder.is_dir() else None
        if not kb_id:
            continue
        for p in sorted(folder.rglob("*.md")):
            heading = p.stem
            for block in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")):
                block = block.strip()
                if not block:
                    continue
                if block.startswith("#") and "\n" not in block:
                    heading = block.lstrip("# ").strip()
                    continue
                out.append(Chunk(kb_id, p.stem, heading, block))
    return out


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def search(query: str, kb_ids: list[str], top_k: int = 5) -> list[dict]:
    """在指定知识库中检索。调用方负责先按权限过滤 kb_ids，这里只会查传进来的库。"""
    if not kb_ids or not query.strip():
        return []
    client = from_settings()
    if client is None:
        return local_search(query, kb_ids, top_k)
    try:
        return _ragflow_search(client, query, kb_ids, top_k)
    except RagflowError as e:
        log.warning("RAGFlow 检索失败，回退本地检索：%s", e)
        return local_search(query, kb_ids, top_k)


def _ragflow_search(client, query: str, kb_ids: list[str], top_k: int) -> list[dict]:
    by_dataset = {}
    for kb_id in kb_ids:
        ds = client.find_dataset(f"{DATASET_PREFIX}{kb_id}")
        if ds:  # 还没同步到 RAGFlow 的库直接跳过，绝不扩大查询范围
            by_dataset[ds] = kb_id
    if not by_dataset:
        return []
    out = []
    for c in client.retrieve(query, list(by_dataset), top_k):
        kb_id = by_dataset.get(c.get("dataset_id"))
        if not kb_id:  # 不属于本次允许的库，丢弃
            continue
        out.append({"knowledge_base": KB_REGISTRY[kb_id]["name"], "kb_id": kb_id,
                    "document": Path(c.get("document_keyword") or "").stem, "section": "",
                    "text": c.get("content", ""), "score": round(float(c.get("similarity") or 0), 3)})
    return out


def local_search(query: str, kb_ids: list[str], top_k: int = 5) -> list[dict]:
    """本地 vault 的关键词检索（RAGFlow 未配置或不可用时的回退）。"""
    q = _bigrams(query)
    scored = []
    for c in _chunks():
        if c.kb_id not in kb_ids:
            continue
        grams = _bigrams(c.heading + c.text)
        score = len(q & grams) / (len(q) or 1)
        if query.strip() and query.strip() in c.text:
            score += 1
        if score > 0.15:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{
        "knowledge_base": KB_REGISTRY[c.kb_id]["name"], "kb_id": c.kb_id, "document": c.doc,
        "section": c.heading, "text": c.text, "score": round(s, 3),
    } for s, c in scored[:top_k]]


def kb_documents(kb_id: str) -> list[dict]:
    meta = KB_REGISTRY[kb_id]
    folder = Path(settings.vault_dir) / meta["name"]
    docs = []
    for i, p in enumerate(sorted(folder.rglob("*.md")) if folder.exists() else []):
        text = p.read_text(encoding="utf-8")
        docs.append({
            "id": f"{kb_id}-f{i + 1}", "title": p.stem, "type": "md",
            "chunks": len([b for b in re.split(r"\n\s*\n", text) if b.strip()]),
            "status": "已索引",
            "updated_at": datetime.fromtimestamp(p.stat().st_mtime).astimezone().replace(microsecond=0).isoformat(),
        })
    return docs
