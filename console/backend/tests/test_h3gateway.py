"""H3 生成网关：客户端、配置（密钥加密、通道联动）与调度服务的 H3 分支。"""

import base64
import dataclasses
import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db, generation, gpu, h3gateway, imageapi, models_api, policy, secretbox, settings_store
from app.main import app

http_client = TestClient(app)
KEY = "h3-secret-key-4321"
NOW = datetime.now().astimezone()
P = policy.Principal(org="o", user_name="u", display_name="U", dept="d", channel=policy.OFFICIAL,
                     pack={"name": "运营", "tools": ["image.cover", "image.generate", "video.generate"], "gpu_quota_minutes": 0})


@pytest.fixture
def store(monkeypatch):
    data: dict = {}
    monkeypatch.setattr(settings_store, "get", lambda k, default=None: data.get(k, default))
    monkeypatch.setattr(settings_store, "put", lambda k, v: data.__setitem__(k, json.loads(json.dumps(v))))
    monkeypatch.setattr(secretbox, "settings", dataclasses.replace(secretbox.settings, file_secret="s3cret"))
    audits = []
    monkeypatch.setattr(models_api, "_audit", lambda user, tool, detail, result="通过": audits.append((tool, detail, result)))
    data["_audits"] = audits
    return data


def fake_gateway(states=("running", "done"), submit_status=200):
    seen = {"requests": [], "states": list(states)}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen["requests"].append((request.method, request.url.path, body, request.headers.get("x-api-key")))
        if request.url.path.startswith("/api/v1/generate/"):
            if submit_status != 200:
                return httpx.Response(submit_status, text=f"bad key {KEY}")
            return httpx.Response(200, json={"job_id": "job1", "status": "queued"})
        if request.url.path == "/api/v1/jobs/job1":
            state = seen["states"].pop(0) if len(seen["states"]) > 1 else seen["states"][0]
            return httpx.Response(200, json={"status": state, "error": "显存不足" if state == "error" else None})
        if request.url.path == "/api/v1/jobs/job1/video":
            return httpx.Response(200, content=b"BYTES")
        return httpx.Response(404)

    return seen, httpx.Client(transport=httpx.MockTransport(handler))


def test_submit_modes_and_payload():
    seen, http = fake_gateway()
    c = h3gateway.H3Client("http://gw:8100", KEY, client=http)
    assert c.submit("t2v", "海边", width=480, height=832, frames=107, fps=24) == "job1"
    _, path, body, key = seen["requests"][-1]
    assert path == "/api/v1/generate/t2v" and key == KEY
    assert body["prompt"] == "海边" and body["width"] == 480 and body["total_frames"] == 107 and "reference_images" not in body
    c.submit("i2v", "慢慢推近", frames=107, image=b"\x89PNG")
    body = seen["requests"][-1][2]
    assert base64.b64decode(body["reference_images"][0]["data_base64"]) == b"\x89PNG" and "width" not in body


def test_poll_states_and_download():
    _, http = fake_gateway(states=("running", "done"))
    c = h3gateway.H3Client("http://gw:8100", KEY, client=http)
    assert c.poll("job1") == ("running", "") and c.poll("job1") == ("done", "")
    assert c.download("job1") == b"BYTES"
    _, http = fake_gateway(states=("error",))
    assert h3gateway.H3Client("http://gw:8100", KEY, client=http).poll("job1") == ("failed", "显存不足")


def test_errors_never_contain_the_key():
    _, http = fake_gateway(submit_status=401)
    with pytest.raises(h3gateway.H3Error) as e:
        h3gateway.H3Client("http://gw:8100", KEY, client=http).submit("t2i", "x")
    assert KEY not in str(e.value) and "401" in str(e.value)


def test_save_gateway_encrypts_masks_and_keeps_key_when_blank(store):
    out = h3gateway.save_gateway("http://192.168.0.41:8100/api/v1/", KEY)
    assert out["base_url"] == "http://192.168.0.41:8100" and out["key_hint"].endswith("4321") and KEY not in json.dumps(out)
    assert KEY not in json.dumps(store[h3gateway.GATEWAY_KEY])
    enc = store[h3gateway.GATEWAY_KEY]["key_enc"]
    h3gateway.save_gateway("http://gw:8100", None, verify_tls=False)
    assert store[h3gateway.GATEWAY_KEY]["key_enc"] == enc and store[h3gateway.GATEWAY_KEY]["verify_tls"] is False
    assert h3gateway.client().key == KEY
    with pytest.raises(h3gateway.H3Error, match="http"):
        h3gateway.save_gateway("gw:8100", KEY)


def test_first_save_needs_key_and_routes_need_a_gateway(store):
    with pytest.raises(h3gateway.H3Error, match="密钥"):
        h3gateway.save_gateway("http://gw:8100", None)
    with pytest.raises(h3gateway.H3Error, match="没有可用的 H3 网关"):
        h3gateway.set_video_route("h3")
    with pytest.raises(imageapi.ImageApiError, match="没有可用的 H3 网关"):
        imageapi.set_route("h3")


def test_disabling_or_deleting_gateway_resets_routes(store):
    h3gateway.save_gateway("http://gw:8100", KEY)
    assert h3gateway.set_video_route("h3") == "h3" and imageapi.set_route("h3") == "h3"
    h3gateway.save_gateway("http://gw:8100", None, enabled=False)
    assert h3gateway.get_video_route() == "gpu" and imageapi.get_route() == "gpu" and h3gateway.client() is None
    h3gateway.save_gateway("http://gw:8100", None, enabled=True)
    h3gateway.set_video_route("h3")
    assert h3gateway.remove_gateway() and h3gateway.get_video_route() == "gpu"


def test_api_endpoints_save_route_and_audit(store):
    r = http_client.put("/api/models/h3", json={"base_url": "http://gw:8100", "key": KEY})
    assert r.status_code == 200 and KEY not in r.text
    assert http_client.put("/api/models/video/route", json={"route": "h3"}).json()["route"] == "h3"
    assert http_client.put("/api/models/image/route", json={"route": "h3"}).json()["route"] == "h3"
    assert http_client.put("/api/models/video/route", json={"route": "bogus"}).status_code == 400
    cfg = http_client.get("/api/models/image").json()
    assert cfg["video_route"] == "h3" and cfg["route"] == "h3" and cfg["h3"]["key_hint"].endswith("4321")
    assert KEY not in json.dumps(cfg)
    assert http_client.delete("/api/models/h3").status_code == 200
    assert http_client.delete("/api/models/h3").status_code == 404
    assert all(KEY not in d for _, d, _ in store["_audits"])
    assert {t for t, _, _ in store["_audits"]} >= {"model.h3.save", "model.video.route"}


# ---- 调度服务的 H3 分支 ----

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
        monkeypatch.setattr(db, "running_api_tasks", lambda wf=db.API_WORKFLOWS: [
            t for t in self.tasks.values() if t["status"] == "running" and t["workflow"] in wf])
        monkeypatch.setattr(db, "claim_api_tasks", self.claim)
        monkeypatch.setattr(db, "update_gpu_task", self.update)

    def claim(self, limit, wf=db.API_WORKFLOWS, node_id="api"):
        running = [t for t in self.tasks.values() if t["status"] == "running" and t["workflow"] in wf]
        out = []
        for t in sorted(self.tasks.values(), key=lambda t: t["id"]):
            if t["status"] == "queued" and t["workflow"] in wf and len(running) + len(out) < limit:
                t.update(status="running", node_id=node_id, started_at=NOW)
                out.append(t)
        return out

    def update(self, tid, **f):
        self.tasks[tid].update(f)


class FakeH3:
    def __init__(self, polls=("done",), submit_error=None):
        self.polls, self.submit_error, self.submitted, self.key = list(polls), submit_error, [], KEY

    def submit(self, mode, prompt, **kw):
        if self.submit_error:
            raise h3gateway.H3Error(self.submit_error)
        self.submitted.append((mode, prompt, kw))
        return f"j{len(self.submitted)}"

    def poll(self, job):
        s = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        return (s, "显存不足" if s == "failed" else "")

    def download(self, job):
        return b"OUT-" + job.encode()


@pytest.fixture
def env(monkeypatch, tmp_path):
    fake = FakeDb(monkeypatch)
    s = dataclasses.replace(gpu.settings, outputs_dir=str(tmp_path), gpu_max_pending_per_user=0, h3_max_concurrency=2)
    for mod in (gpu, generation):
        monkeypatch.setattr(mod, "settings", s)
    monkeypatch.setattr(imageapi, "get_route", lambda: "h3")
    monkeypatch.setattr(h3gateway, "get_video_route", lambda: "h3")
    monkeypatch.setattr(generation, "_image_ext", lambda data: ".png")
    fake.tmp = tmp_path
    return fake


def step(client, now=None):
    gpu.run_h3_step(client_factory=lambda: client, now=now)


def test_routes_decide_h3_workflows(env, monkeypatch):
    assert generation.submit_image(P, "t", "一只猫")["workflow"] == "h3-image"
    assert generation.submit_video(P, "t", "海边")["workflow"] == "h3-video"
    monkeypatch.setattr(h3gateway, "get_video_route", lambda: "gpu")
    monkeypatch.setattr(imageapi, "get_route", lambda: "gpu")
    assert generation.submit_video(P, "t", "海边")["workflow"] == "video-h3"
    assert generation.submit_image(P, "t", "一只猫")["workflow"] == "image-gen"


def test_image_task_submits_one_job_per_image_and_collects(env):
    t = generation.submit_image(P, "t", "一只猫", aspect="3:4", count=2)
    c = FakeH3(polls=("running", "done"))  # 每轮每个网关任务各消耗一个状态：第一轮 j1 在跑、j2 完成，第二轮全部完成
    step(c)
    row = env.tasks[t["id"]]
    assert row["prompt_id"] == "j1,j2" and row["node_id"] == "h3"
    assert [m for m, _, _ in c.submitted] == ["t2i", "t2i"] and c.submitted[0][2]["width"] == 768
    step(c)
    assert env.tasks[t["id"]]["status"] == "running"
    step(c)
    row = env.tasks[t["id"]]
    assert row["status"] == "done" and row["images"] == ["1.png", "2.png"]
    assert (env.tmp / t["id"] / "2.png").read_bytes() == b"OUT-j2" and len(c.submitted) == 2
    assert "H3 网关" in env.audits[-1]["detail"] and env.audits[-1]["result"] == "通过"


def test_video_text_and_image_modes(env):
    t = generation.submit_video(P, "t", "海边", aspect="9:16", seconds=4)
    c = FakeH3()
    step(c)
    assert c.submitted[0][0] == "t2v" and c.submitted[0][2]["frames"] == 107 and c.submitted[0][2]["width"] == 480
    step(c)
    assert env.tasks[t["id"]]["images"] == ["1.mp4"]
    img = b"\x89PNG\r\n\x1a\n" + b"0" * 10
    generation.submit_video_from_image(P, "t", img, "慢慢推近", seconds=4)
    c2 = FakeH3()
    step(c2)
    mode, _, kw = c2.submitted[0]
    assert mode == "i2v" and kw["image"] == img and kw["width"] is None


def test_failures_mark_task_failed_with_audit(env):
    for client, expect in ((FakeH3(polls=("failed",)), "显存不足"), (FakeH3(submit_error="HTTP 401"), "401")):
        t = generation.submit_image(P, "t", "一只猫")
        step(client)
        step(client)
        row = env.tasks[t["id"]]
        assert row["status"] == "failed" and expect in row["error"], row
        assert env.audits[-1]["result"] == "拒绝"


def test_restart_resumes_without_resubmitting_and_timeout_fails(env):
    t = generation.submit_video(P, "t", "海边")
    c = FakeH3(polls=("running",))
    step(c)
    assert len(c.submitted) == 1
    step(c)  # 重启后的下一轮：只轮询，不重复提交
    assert len(c.submitted) == 1 and env.tasks[t["id"]]["status"] == "running"
    step(c, now=NOW + timedelta(minutes=41))
    assert env.tasks[t["id"]]["status"] == "failed" and "超时" in env.tasks[t["id"]]["error"]


def test_concurrency_limit_and_missing_gateway(env):
    for _ in range(3):
        generation.submit_image(P, "t", "一只猫")
    step(FakeH3(polls=("running",)))
    assert sum(1 for t in env.tasks.values() if t["status"] == "running") == 2
    for t in env.tasks.values():
        t["status"] = "failed"
    t = generation.submit_image(P, "t", "一只猫")
    gpu.run_h3_step(client_factory=lambda: None)
    assert env.tasks[t["id"]]["status"] == "failed" and "没有可用的 H3 网关" in env.tasks[t["id"]]["error"]
