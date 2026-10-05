import asyncio
import time

from searxng_control.config import Config
from searxng_control.hub import Hub
from searxng_control.notify import save_settings


def make_hub(tmp_path):
    (tmp_path / "sx" / "config").mkdir(parents=True)
    hub = Hub(Config(data_dir=tmp_path / "data", settings_file=tmp_path / "sx" / "config" / "settings.yml",
                     enable_docker=False, update_method="agent"))
    hub.container = {"image_labels": {"org.opencontainers.image.version": "2026.10.2-19ffbcd30"}}
    (hub.queue.root / "agent-heartbeat").write_text(str(int(time.time())))
    return hub


def snap(pushed_hours_ago=3.0, relevant=(), states=None):
    pushed = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - pushed_hours_ago * 3600))
    return {"upstream": {"update_available": True, "latest": {"tag": "2026.10.4-d48c4b555", "pushed": pushed},
                         "image_behind": {"relevant_engines": list(relevant)}},
            "states": states or {}}


def test_always_mode_queues_once_and_respects_spacing(tmp_path):
    hub = make_hub(tmp_path)
    assert asyncio.run(hub.maybe_auto_update(snap())) == "new image available"
    assert len(hub.queue.pending_jobs("update")) == 1
    assert asyncio.run(hub.maybe_auto_update(snap())) is None          # job already pending
    for p in hub.queue.pending.glob("*.json"):
        p.unlink()
    assert asyncio.run(hub.maybe_auto_update(snap())) is None          # same tag tried recently


def test_fresh_image_waits_but_fix_goes_now(tmp_path):
    hub = make_hub(tmp_path)
    assert asyncio.run(hub.maybe_auto_update(snap(pushed_hours_ago=0.2))) is None
    s = snap(pushed_hours_ago=0.2, relevant=["startpage"], states={"startpage": {"status": "blocked"}})
    assert asyncio.run(hub.maybe_auto_update(s)) == "fix for startpage"


def test_off_and_fixes_modes(tmp_path):
    hub = make_hub(tmp_path)
    save_settings(hub.db, {"auto_update": "off"})
    assert asyncio.run(hub.maybe_auto_update(snap(relevant=["x"], states={"x": {"status": "failing"}}))) is None
    save_settings(hub.db, {"auto_update": "fixes"})
    assert asyncio.run(hub.maybe_auto_update(snap())) is None
    assert asyncio.run(hub.maybe_auto_update(snap(relevant=["x"], states={"x": {"status": "failing"}}))) == "fix for x"


def test_no_agent_no_update(tmp_path):
    hub = make_hub(tmp_path)
    (hub.queue.root / "agent-heartbeat").write_text(str(int(time.time()) - 3600))
    assert asyncio.run(hub.maybe_auto_update(snap())) is None


def test_docker_mode_without_docker_never_queues(tmp_path):
    hub = make_hub(tmp_path)
    object.__setattr__(hub.cfg, "update_method", "docker")
    assert asyncio.run(hub.maybe_auto_update(snap())) is None
