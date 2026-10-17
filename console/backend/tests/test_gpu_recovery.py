"""GPU 调度的容错：节点掉线 / 派发中断 / 超时自动改派（最多重试 1 次），网络抖动不判失败。"""

from datetime import datetime, timedelta

import httpx
import pytest

from app import db, gpu

NOW = datetime.now().astimezone()
NODES = {"n1": {"id": "n1", "name": "GPU-01", "url": "http://n1"}}


def task(**kw):
    base = {"id": "t1", "trace_id": "tr", "org": "o", "user_name": "u", "display_name": "U", "dept": "d", "channel": "c",
            "workflow": "image-gen", "params": {"title": "猫", "_outputs": ["9"]}, "node_id": "n1", "prompt_id": "p1",
            "started_at": NOW - timedelta(seconds=40), "attempts": 0}
    return {**base, **kw}


@pytest.fixture
def rec(monkeypatch):
    calls = {"requeue": [], "update": [], "audit": [], "cancel": []}
    monkeypatch.setattr(db, "requeue_gpu_task", lambda tid: calls["requeue"].append(tid))
    monkeypatch.setattr(db, "update_gpu_task", lambda tid, **f: calls["update"].append((tid, f)))
    monkeypatch.setattr(db, "add_audit", lambda **e: calls["audit"].append(e))

    class FakeComfy:
        def __init__(self, url):
            pass

        def cancel(self, prompt_id):
            calls["cancel"].append(prompt_id)

        def result(self, prompt_id, outputs):
            raise httpx.ConnectError("连接被拒绝")
    monkeypatch.setattr(gpu, "ComfyUI", FakeComfy)
    return calls


def run(monkeypatch, tasks, online):
    monkeypatch.setattr(db, "running_tasks", lambda: tasks)
    gpu._recover(NODES, online, NOW)


def test_offline_node_requeues_once(monkeypatch, rec):
    run(monkeypatch, [task()], online=set())
    assert rec["requeue"] == ["t1"] and rec["update"] == []
    assert "重新排队" in rec["audit"][-1]["detail"] and "掉线" in rec["audit"][-1]["detail"]


def test_second_failure_marks_failed(monkeypatch, rec):
    run(monkeypatch, [task(attempts=1)], online=set())
    assert rec["requeue"] == [] and rec["update"][0][1]["status"] == "failed"
    assert rec["audit"][-1]["result"] == "拒绝"


def test_offline_grace_period(monkeypatch, rec):
    run(monkeypatch, [task(started_at=NOW - timedelta(seconds=10))], online=set())  # 刚派发，节点状态可能还没刷新
    assert rec["requeue"] == [] and rec["update"] == []


def test_dispatch_interrupted_without_prompt_id(monkeypatch, rec):
    run(monkeypatch, [task(prompt_id=None, started_at=NOW - timedelta(seconds=150))], online={"n1"})
    assert rec["requeue"] == ["t1"]


def test_timeout_cancels_on_comfyui_then_requeues(monkeypatch, rec):
    run(monkeypatch, [task(workflow="image-gen", started_at=NOW - timedelta(minutes=11))], online={"n1"})
    assert rec["cancel"] == ["p1"] and rec["requeue"] == ["t1"]
    assert "超时" in rec["audit"][-1]["detail"]


def test_video_gets_longer_timeout(monkeypatch, rec):
    run(monkeypatch, [task(workflow="video-h3", started_at=NOW - timedelta(minutes=11))], online={"n1"})
    assert rec["requeue"] == [] and rec["cancel"] == []


def test_healthy_running_task_untouched(monkeypatch, rec):
    run(monkeypatch, [task()], online={"n1"})
    assert rec["requeue"] == [] and rec["update"] == [] and rec["audit"] == []


def test_collect_network_blip_does_not_fail(monkeypatch, rec):
    monkeypatch.setattr(db, "running_tasks", lambda: [task()])
    gpu._collect(NODES)
    assert rec["update"] == [] and rec["audit"] == []
