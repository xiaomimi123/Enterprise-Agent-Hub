"""API 出图接入任务队列：通道开关决定新任务的 workflow；worker 的 API 分支提交、轮询、落盘、容错。"""

import dataclasses
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import db, generation, gpu, imageapi, policy

NOW = datetime.now().astimezone()
P = policy.Principal(org="o", user_name="u", display_name="U", dept="d", channel=policy.OFFICIAL,
                     pack={"name": "运营", "tools": ["image.cover", "image.generate"], "gpu_quota_minutes": 0})


class FakeDb:
    def __init__(self, monkeypatch):
        self.tasks: dict[str, dict] = {}
        self.audits: list[dict] = []
        monkeypatch.setattr(db, "create_gpu_task", lambda t: self.tasks.__setitem__(t["id"], {
            **t, "status": "queued", "node_id": None, "prompt_id": None, "images": [], "error": "", "attempts": 0,
            "created_at": NOW, "started_at": None, "finished_at": None}))
        monkeypatch.setattr(db, "queue_position", lambda tid: 0)
        monkeypatch.setattr(db, "pending_task_count", lambda org, user: 0)
        monkeypatch.setattr(db, "gpu_seconds_this_month", lambda org, user: 0)
        monkeypatch.setattr(db, "add_audit", lambda **e: self.audits.append(e))
        monkeypatch.setattr(db, "running_api_tasks", lambda: [t for t in self.tasks.values()
                                                              if t["status"] == "running" and t["workflow"] == "api-image"])
        monkeypatch.setattr(db, "claim_api_tasks", self.claim)
        monkeypatch.setattr(db, "update_gpu_task", self.update)
        monkeypatch.setattr(db, "requeue_gpu_task", self.requeue)

    def claim(self, limit):
        running = [t for t in self.tasks.values() if t["status"] == "running" and t["workflow"] == "api-image"]
        out = []
        for t in sorted(self.tasks.values(), key=lambda t: t["id"]):
            if t["status"] == "queued" and t["workflow"] == "api-image" and len(running) + len(out) < limit:
                t.update(status="running", node_id="api", started_at=NOW)
                out.append(t)
        return out

    def update(self, tid, **f):
        self.tasks[tid].update(f)
        if f.get("status") in ("done", "failed"):
            self.tasks[tid]["finished_at"] = NOW

    def requeue(self, tid):
        self.tasks[tid].update(status="queued", node_id=None, prompt_id=None, started_at=None,
                               attempts=self.tasks[tid]["attempts"] + 1)


class FakeClient:
    def __init__(self, polls=("done",), urls=("u1", "u2"), submit_error=None):
        self.polls, self.urls, self.submit_error = list(polls), list(urls), submit_error
        self.submitted = []
        self.key = "k"

    def submit(self, prompt, width, height, count):
        if self.submit_error:
            raise imageapi.ImageApiError(self.submit_error)
        self.submitted.append((prompt, width, height, count))
        return f"ext-{len(self.submitted)}"

    def poll(self, task_id):
        state = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        return state, (self.urls if state == "done" else [])

    def download(self, url):
        return b"IMG-" + url.encode()


@pytest.fixture
def env(monkeypatch, tmp_path):
    fake = FakeDb(monkeypatch)
    s = dataclasses.replace(gpu.settings, outputs_dir=str(tmp_path), gpu_max_pending_per_user=0, image_api_max_concurrency=4)
    for mod in (gpu, generation):
        monkeypatch.setattr(mod, "settings", s)
    monkeypatch.setattr(imageapi, "get_route", lambda: "gpu")
    monkeypatch.setattr(imageapi, "default_provider", lambda: {"id": "pv1", "name": "apimart"})
    fake.tmp = tmp_path
    return fake


def step(client, monkeypatch=None):
    gpu.run_api_step(client_factory=lambda provider_id: client)


def submit(env, monkeypatch, route, **kw):
    monkeypatch.setattr(imageapi, "get_route", lambda: route)
    return generation.submit_image(P, "tr-1", "一只猫", **kw)


def test_route_decides_workflow_for_new_tasks(env, monkeypatch):
    assert submit(env, monkeypatch, "gpu")["workflow"] == "image-gen"
    assert submit(env, monkeypatch, "api")["workflow"] == "api-image"
    monkeypatch.setattr(imageapi, "get_route", lambda: "api")
    cover = generation.submit_cover(P, "tr-2", "秋冬保湿", None)
    assert cover["workflow"] == "api-image" and cover["params"]["count"] == 3
    assert env.tasks[cover["id"]]["params"]["tool"] == "image.cover"


def test_api_task_is_submitted_then_collected_to_outputs(env, monkeypatch):
    t = submit(env, monkeypatch, "api", count=2)
    client = FakeClient(polls=("running", "done"))
    step(client)
    row = env.tasks[t["id"]]
    assert row["status"] == "running" and row["prompt_id"] == "ext-1" and row["params"]["_provider"] == "pv1"
    assert client.submitted == [("一只猫", 1024, 1024, 2)]
    step(client)                                                         # 仍在跑
    assert env.tasks[t["id"]]["status"] == "running"
    step(client)
    row = env.tasks[t["id"]]
    assert row["status"] == "done" and row["images"] == ["1.png", "2.png"]
    assert (env.tmp / t["id"] / "1.png").read_bytes() == b"IMG-u1"
    assert "第三方 API" in env.audits[-1]["detail"] and env.audits[-1]["result"] == "通过"
    assert len(client.submitted) == 1                                    # 没有重复提交


def test_failed_empty_and_submit_error_mark_task_failed_with_audit(env, monkeypatch):
    for client, expect in ((FakeClient(polls=("failed",)), "失败"), (FakeClient(urls=()), "没有返回图片"),
                           (FakeClient(submit_error="HTTP 401"), "401")):
        t = submit(env, monkeypatch, "api")
        step(client)
        step(client)
        row = env.tasks[t["id"]]
        assert row["status"] == "failed" and expect in row["error"], (expect, row)
        assert env.audits[-1]["result"] == "拒绝"


def test_timeout_fails_running_task(env, monkeypatch):
    t = submit(env, monkeypatch, "api")
    step(FakeClient(polls=("running",)))
    env.tasks[t["id"]]["started_at"] = NOW - timedelta(seconds=gpu.API_TIMEOUT_SECONDS + 5)
    step(FakeClient(polls=("running",)))
    assert env.tasks[t["id"]]["status"] == "failed" and "超时" in env.tasks[t["id"]]["error"]


def test_restart_resumes_polling_without_resubmitting(env, monkeypatch):
    t = submit(env, monkeypatch, "api")
    env.tasks[t["id"]].update(status="running", node_id="api", started_at=NOW, prompt_id="ext-9",
                              params={**env.tasks[t["id"]]["params"], "_provider": "pv1"})
    client = FakeClient(polls=("done",))
    step(client)
    assert client.submitted == [] and env.tasks[t["id"]]["status"] == "done"


def test_dispatch_interrupted_before_task_id_requeues_once_then_fails(env, monkeypatch):
    t = submit(env, monkeypatch, "api")
    row = env.tasks[t["id"]]
    row.update(status="running", node_id="api", started_at=NOW - timedelta(seconds=gpu.DISPATCH_GRACE + 5))
    step(FakeClient())
    assert row["status"] in ("queued", "running") and row["attempts"] == 1       # 重新排队后同一轮又被领取、提交
    row.update(status="running", prompt_id=None, started_at=NOW - timedelta(seconds=gpu.DISPATCH_GRACE + 5))
    step(FakeClient())
    assert row["status"] == "failed"


def test_concurrency_limit(env, monkeypatch):
    for _ in range(6):
        submit(env, monkeypatch, "api")
    client = FakeClient(polls=("running",))
    step(client)
    assert len(client.submitted) == 4


def test_switching_route_does_not_touch_existing_tasks(env, monkeypatch):
    t = submit(env, monkeypatch, "api")
    submit(env, monkeypatch, "gpu")
    assert env.tasks[t["id"]]["workflow"] == "api-image"
    step(FakeClient(polls=("done",)))                                    # 通道已切回 gpu，旧的 API 任务仍由 API 完成
    assert env.tasks[t["id"]]["status"] == "running" and env.tasks[t["id"]]["prompt_id"] == "ext-1"


def test_no_provider_fails_queued_api_task(env, monkeypatch):
    monkeypatch.setattr(imageapi, "default_provider", lambda: None)
    t = submit(env, monkeypatch, "api")
    step(FakeClient())
    assert env.tasks[t["id"]]["status"] == "failed" and "没有可用的出图 API" in env.tasks[t["id"]]["error"]


def test_list_tasks_shows_channel(env, monkeypatch):
    a, g = submit(env, monkeypatch, "api"), submit(env, monkeypatch, "gpu")
    monkeypatch.setattr(db, "recent_gpu_tasks", lambda limit: list(env.tasks.values()))
    monkeypatch.setattr(gpu, "file_url", lambda tid, n: f"u/{tid}/{n}")
    vias = {t["id"]: t["via"] for t in gpu.list_tasks()["tasks"]}
    assert vias[a["id"]] == "第三方 API" and vias[g["id"]] == "本机 GPU"
