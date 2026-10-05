import time

from searxng_control.alerts import evaluate
from searxng_control.notify import DEFAULT_SETTINGS


def test_low_engines_and_blocked_engine():
    now = time.time()
    snap = {
        "docker_ok": True, "container": {"state": "running"}, "have_data": True,
        "web_engines": ["a", "b", "c", "d"],
        "states": {"a": {"status": "healthy"}, "b": {"status": "blocked", "failing_since": now - 5 * 3600, "last_error": {"kind": "captcha"}},
                   "c": {"status": "failing", "failing_since": now - 600}, "d": {"status": "healthy"}},
        "upstream": {}, "last_update_log": "2026-10-05 up to date", "agent_heartbeat": now,
    }
    keys = {k for k, *_ in evaluate(snap, DEFAULT_SETTINGS)}
    assert "web_engines_low" in keys
    assert "engine_down:b" in keys and "engine_down:c" not in keys


def test_fix_available():
    snap = {
        "docker_ok": True, "container": {"state": "running"}, "have_data": True, "web_engines": ["startpage"],
        "states": {"startpage": {"status": "blocked", "last_ok": None}},
        "upstream": {"update_available": True, "latest": {"tag": "2026.10.6-abc", "pushed": "2026-10-06T00:00:00Z"},
                     "image_behind": {"relevant_engines": ["startpage"], "ahead_by": 3}},
    }
    keys = {k for k, *_ in evaluate(snap, DEFAULT_SETTINGS)}
    assert "fix_available" in keys and "container_down" not in keys
