import os
import time

from app.core import heartbeat


def test_fresh_beat_is_healthy_and_a_stale_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(heartbeat, "FILE", tmp_path / "alive")
    assert not heartbeat.healthy(60)  # never beat yet: a worker stuck at start counts as stuck
    heartbeat.beat()
    assert heartbeat.healthy(60)
    old = time.time() - 120
    os.utime(heartbeat.FILE, (old, old))
    assert not heartbeat.healthy(60)
