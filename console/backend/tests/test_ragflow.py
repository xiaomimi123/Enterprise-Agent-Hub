import json

import httpx
import pytest

from app import ragflow
from app.ragflow import Ragflow, RagflowError


def make(handler) -> tuple[Ragflow, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    return Ragflow("http://rf:9380", "key-1", transport=httpx.MockTransport(wrapped)), seen


def ok(data=None) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": data})


def test_requests_carry_bearer_key():
    rf, seen = make(lambda r: ok([]))
    rf.find_dataset("hub-kb-brand")
    assert seen[0].headers["Authorization"] == "Bearer key-1"


def test_ensure_dataset_reuses_existing_and_creates_missing():
    def handler(req):
        if req.method == "GET":
            return ok([{"id": "ds-1", "name": "hub-kb-brand"}])
        return ok({"id": "ds-new", "name": json.loads(req.content)["name"]})

    rf, seen = make(handler)
    assert rf.ensure_dataset("hub-kb-brand") == "ds-1"
    assert [r.method for r in seen] == ["GET"]  # 已存在：不创建

    rf, seen = make(handler)
    assert rf.ensure_dataset("hub-kb-hr", "人事") == "ds-new"
    post = next(r for r in seen if r.method == "POST")
    assert post.url.path == "/api/v1/datasets" and json.loads(post.content)["name"] == "hub-kb-hr"
    assert "embedding_model" not in json.loads(post.content)  # 不指定时用租户默认

    rf, seen = make(handler)
    rf.ensure_dataset("hub-kb-hr", embedding_model="Qwen/Qwen3-Embedding-0.6B@Builtin")
    assert json.loads(next(r for r in seen if r.method == "POST").content)["embedding_model"] == "Qwen/Qwen3-Embedding-0.6B@Builtin"


def test_find_dataset_matches_locally_and_pages():
    pages = {"1": [{"id": f"x{i}", "name": f"n{i}"} for i in range(100)], "2": [{"id": "hit", "name": "hub-kb-hr"}]}
    rf, seen = make(lambda r: ok(pages[r.url.params["page"]]))
    assert rf.find_dataset("hub-kb-hr") == "hit"
    assert all("name" not in r.url.params for r in seen)  # 不传 name 过滤
    assert make(lambda r: ok([]))[0].find_dataset("nope") is None


def test_retrieve_sends_scope_and_page_size():
    rf, seen = make(lambda r: ok({"chunks": [{"content": "c", "dataset_id": "ds-1"}], "total": 1}))
    chunks = rf.retrieve("保湿", ["ds-1", "ds-2"], top_k=3)
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/v1/retrieval"
    assert body["question"] == "保湿" and body["dataset_ids"] == ["ds-1", "ds-2"] and body["page_size"] == 3
    assert chunks == [{"content": "c", "dataset_id": "ds-1"}]


def test_error_code_raises_with_message():
    rf, _ = make(lambda r: httpx.Response(200, json={"code": 102, "message": "`dataset_ids` is required."}))
    with pytest.raises(RagflowError, match="dataset_ids"):
        rf.retrieve("x", [])


def test_http_failure_raises():
    rf, _ = make(lambda r: httpx.Response(502, text="bad gateway"))
    with pytest.raises(RagflowError):
        rf.find_dataset("a")


def test_from_settings_requires_endpoint_and_key(monkeypatch):
    import dataclasses
    for endpoint, key, expect in (("", "k", False), ("http://rf", "", False), ("http://rf", "k", True)):
        monkeypatch.setattr(ragflow, "settings", dataclasses.replace(ragflow.settings, ragflow_endpoint=endpoint, ragflow_api_key=key))
        assert (ragflow.from_settings() is not None) is expect


# ---- content.search 切换到 RAGFlow ----

from app import content  # noqa: E402


class FakeRagflow:
    def __init__(self, datasets: dict[str, str], chunks=None, error: Exception | None = None):
        self.datasets, self.chunks, self.error, self.retrieved = datasets, chunks or [], error, []

    def find_dataset(self, name):
        return self.datasets.get(name)

    def retrieve(self, question, dataset_ids, top_k=5):
        self.retrieved.append((question, list(dataset_ids), top_k))
        if self.error:
            raise self.error
        return self.chunks


def use(monkeypatch, fake):
    monkeypatch.setattr(content, "from_settings", lambda: fake)


def test_search_maps_chunks_and_scopes_datasets(monkeypatch):
    fake = FakeRagflow({"hub-kb-brand": "ds-brand", "hub-kb-finance": "ds-fin"}, chunks=[
        {"content": "秋冬主张：温暖", "dataset_id": "ds-brand", "document_keyword": "2026秋冬品牌主张.md", "similarity": 0.8123456},
    ])
    use(monkeypatch, fake)
    hits = content.search("品牌主张", ["kb-brand"])
    assert fake.retrieved == [("品牌主张", ["ds-brand"], 5)]  # 只查有权限的库，不含财务
    assert hits == [{"knowledge_base": "品牌调性与人设", "kb_id": "kb-brand", "document": "2026秋冬品牌主张",
                     "section": "", "text": "秋冬主张：温暖", "score": 0.812}]


def test_search_skips_empty_inputs(monkeypatch):
    fake = FakeRagflow({"hub-kb-brand": "ds-brand"})
    use(monkeypatch, fake)
    assert content.search("品牌", []) == []
    assert content.search("   ", ["kb-brand"]) == []
    assert fake.retrieved == []


def test_search_skips_kb_without_dataset(monkeypatch):
    fake = FakeRagflow({"hub-kb-brand": "ds-brand"})
    use(monkeypatch, fake)
    content.search("x", ["kb-brand", "kb-hr"])  # kb-hr 还没同步：跳过，不扩大范围
    assert fake.retrieved[0][1] == ["ds-brand"]
    fake.retrieved.clear()
    assert content.search("x", ["kb-hr"]) == [] and fake.retrieved == []


def test_search_falls_back_to_local_on_error(monkeypatch):
    use(monkeypatch, FakeRagflow({"hub-kb-product": "ds-p"}, error=RagflowError("down")))
    hits = content.search("保湿精华", ["kb-product"])
    assert hits and all(h["kb_id"] == "kb-product" for h in hits)  # 本地 vault 的结果


def test_search_uses_local_when_not_configured(monkeypatch):
    use(monkeypatch, None)
    assert content.search("保湿精华", ["kb-product"]) == content.local_search("保湿精华", ["kb-product"])


# ---- vault → RAGFlow 同步 ----

from app import kb_sync  # noqa: E402


class SyncFake:
    """内存里的 RAGFlow：记录上传、删除和解析。"""

    def __init__(self):
        self.datasets: dict[str, dict[str, dict]] = {}   # 数据集名 → {文档名: {id, size}}
        self.calls: list[tuple] = []
        self._n = 0

    def ensure_dataset(self, name, description="", embedding_model=None):
        self.models = getattr(self, "models", {}) | {name: embedding_model}
        self.datasets.setdefault(name, {})
        return name

    def list_documents(self, ds):
        return [{"id": v["id"], "name": k, "size": v["size"], "run": "DONE"} for k, v in self.datasets[ds].items()]

    def upload(self, ds, filename, data):
        self._n += 1
        self.datasets[ds][filename] = {"id": f"d{self._n}", "size": len(data)}
        self.calls.append(("upload", ds, filename))
        return f"d{self._n}"

    def delete_documents(self, ds, ids):
        self.datasets[ds] = {k: v for k, v in self.datasets[ds].items() if v["id"] not in ids}
        self.calls.append(("delete", ds, tuple(ids)))

    def parse(self, ds, ids):
        self.calls.append(("parse", ds, tuple(ids)))


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "品牌调性与人设").mkdir()
    (tmp_path / "品牌调性与人设" / "a.md").write_text("# 主张\n温暖", encoding="utf-8")
    (tmp_path / "品牌调性与人设" / "b.md").write_text("人设", encoding="utf-8")
    (tmp_path / "不在注册表的文件夹").mkdir()
    (tmp_path / "不在注册表的文件夹" / "x.md").write_text("忽略我", encoding="utf-8")
    return tmp_path


def test_first_sync_uploads_and_parses_everything(vault):
    rf = SyncFake()
    stats = kb_sync.sync_vault(rf, str(vault))
    assert stats == {"uploaded": 2, "updated": 0, "deleted": 0, "skipped": 0}
    assert set(rf.datasets) == {"hub-kb-brand"}  # 不在注册表的文件夹被忽略，没建数据集
    assert [c[0] for c in rf.calls].count("parse") == 1
    assert rf.models["hub-kb-brand"] == "Qwen/Qwen3-Embedding-0.6B@Builtin"  # 建库时指定内置 TEI 嵌入模型


def test_resync_unchanged_is_a_noop(vault):
    rf = SyncFake()
    kb_sync.sync_vault(rf, str(vault))
    rf.calls.clear()
    assert kb_sync.sync_vault(rf, str(vault)) == {"uploaded": 0, "updated": 0, "deleted": 0, "skipped": 2}
    assert rf.calls == []


def test_changed_file_is_replaced_and_removed_file_is_deleted(vault):
    rf = SyncFake()
    kb_sync.sync_vault(rf, str(vault))
    (vault / "品牌调性与人设" / "a.md").write_text("# 主张\n温暖而且更长", encoding="utf-8")
    (vault / "品牌调性与人设" / "b.md").unlink()
    rf.calls.clear()
    stats = kb_sync.sync_vault(rf, str(vault))
    assert stats == {"uploaded": 0, "updated": 1, "deleted": 1, "skipped": 0}
    kinds = [c[0] for c in rf.calls]
    assert kinds.index("delete") < kinds.index("upload")  # 先删旧文档再传新文档
    assert set(rf.datasets["hub-kb-brand"]) == {"a.md"}


# ---- 终审发现的问题 ----

def test_non_json_response_is_a_ragflow_error():
    rf, _ = make(lambda r: httpx.Response(200, text="<html>502 Bad Gateway</html>"))
    with pytest.raises(RagflowError):
        rf.retrieve("x", ["ds"])


def test_dataset_lookups_are_cached_per_client():
    rf, seen = make(lambda r: ok([{"id": "ds-1", "name": "hub-kb-brand"}]))
    assert rf.find_dataset("hub-kb-brand") == "ds-1" and rf.find_dataset("hub-kb-brand") == "ds-1"
    assert len(seen) == 1                      # 第二次命中缓存
    assert rf.find_dataset("hub-kb-hr") is None  # 未命中的不缓存：同步完成后立刻可见
    assert rf.find_dataset("hub-kb-hr") is None
    assert len(seen) == 3


def test_from_settings_reuses_one_client(monkeypatch):
    import dataclasses
    monkeypatch.setattr(ragflow, "settings", dataclasses.replace(ragflow.settings, ragflow_endpoint="http://rf", ragflow_api_key="k"))
    monkeypatch.setattr(ragflow, "_client", None)
    assert ragflow.from_settings() is ragflow.from_settings()


# ---- 控制台知识库页读 RAGFlow 的真实状态 ----

class DocsFake(FakeRagflow):
    def __init__(self, datasets, docs, error=None):
        super().__init__(datasets, error=error)
        self.docs = docs

    def list_documents(self, ds):
        if self.error:
            raise self.error
        return self.docs.get(ds, [])


def test_kb_documents_reads_ragflow_status(monkeypatch):
    use(monkeypatch, DocsFake({"hub-kb-brand": "ds-b"}, {"ds-b": [
        {"id": "d1", "name": "品牌人设定义.md", "run": "DONE", "chunk_count": 3, "update_time": 1792222473000},
        {"id": "d2", "name": "2026秋冬品牌主张.md", "run": "RUNNING", "chunk_count": 0, "update_time": 1792222473000},
        {"id": "d3", "name": "坏文件.md", "run": "FAIL", "chunk_count": 0, "update_time": 1792222473000},
        {"id": "d4", "name": "新文件.md", "run": "UNSTART", "chunk_count": 0, "update_time": 1792222473000},
    ]}))
    docs = content.kb_documents("kb-brand")
    assert [(d["title"], d["status"], d["chunks"]) for d in docs] == [
        ("品牌人设定义", "已索引", 3), ("2026秋冬品牌主张", "索引中", 0), ("坏文件", "索引失败", 0), ("新文件", "待索引", 0)]
    assert docs[0]["id"] == "d1" and docs[0]["type"] == "md" and docs[0]["updated_at"].startswith("2026-")


def test_kb_documents_falls_back_to_local(monkeypatch):
    use(monkeypatch, DocsFake({}, {}))                     # 还没同步到 RAGFlow
    assert content.kb_documents("kb-product") == content.local_kb_documents("kb-product")
    use(monkeypatch, DocsFake({"hub-kb-product": "ds"}, {}, error=RagflowError("down")))
    assert content.kb_documents("kb-product") == content.local_kb_documents("kb-product")
