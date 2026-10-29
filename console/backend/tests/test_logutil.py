"""降级不能悄无声息：读不到辅助数据时仍然退回默认值，但要留日志，且同一处不刷屏。"""
import logging

from app import logutil, newapi


def test_warn_throttled_logs_once_per_window_per_key(caplog):
    log = logging.getLogger("hub.test")
    logutil._last.clear()
    with caplog.at_level(logging.WARNING, logger="hub.test"):
        assert logutil.warn_throttled(log, "k1", "第一次", now=1000.0) is True
        assert logutil.warn_throttled(log, "k1", "窗口内重复", now=1000.0 + 599) is False
        assert logutil.warn_throttled(log, "k2", "另一个 key 不受影响", now=1000.0 + 1) is True
        assert logutil.warn_throttled(log, "k1", "窗口过后再记", now=1000.0 + 601) is True
    assert [r.getMessage() for r in caplog.records] == ["第一次", "另一个 key 不受影响", "窗口过后再记"]


def test_price_lookup_failure_still_returns_empty_but_leaves_a_log(monkeypatch, caplog):
    logutil._last.clear()
    na = newapi.NewApi("http://x", "t", "1")

    def boom(models):
        raise RuntimeError("网关连不上")
    monkeypatch.setattr(na, "get_pricing", boom)
    with caplog.at_level(logging.WARNING, logger="hub.newapi"):
        assert na.price_table(["m"]) == {}
    assert any("读取模型价格失败" in r.getMessage() for r in caplog.records)


def test_no_silent_broad_except_left_in_app_code():
    """app/ 里的 `except Exception` 必须记日志（log.* / warn_throttled / 重新抛出 / 写入任务错误），不能 pass 或只 return 默认值。"""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "app"
    bad = []
    for f in root.rglob("*.py"):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, l in enumerate(lines):
            if re.match(r"\s*except Exception\b", l):
                body = "\n".join(lines[i:i + 6])
                if not re.search(r"log\.|warn_throttled|raise\b|update_gpu_task|_audit|execute\(", body):
                    bad.append(f"{f.relative_to(root)}:{i + 1}")
    assert not bad, "这些 except Exception 没有留日志：\n" + "\n".join(bad)
