"""The Hub owns all clients, caches and background collectors."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Any

from . import analytics, catalog, settings_editor as se
from .alerts import AlertManager
from .applier import Applier
from .config import Config
from .db import DB
from .docker_api import Docker, DockerError
from .hostqueue import HostQueue
from .logparse import KIND_LABELS, Event, LogParser, Startup
from .notify import Notifier, get_settings, save_settings
from .searxng_client import SearXNG
from .upstream import Upstream, parse_version
from .updater import DockerUpdater

log = logging.getLogger(__name__)

CANARY_QUERIES = [
    "linux kernel scheduler", "how to cook rice", "weather radar", "python dataclass default factory",
    "national parks in utah", "best budget mechanical keyboard", "sourdough starter ratio", "rust borrow checker",
    "wireguard vs openvpn", "history of the printing press", "how do heat pumps work", "postgres vacuum full",
    "james webb telescope images", "raid 5 vs raid 6", "deep dish pizza recipe", "nvme vs sata ssd",
]


class Hub:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = DB(cfg.db_path)
        self.docker = Docker(cfg.docker_socket) if cfg.enable_docker else None
        self.sx = SearXNG(cfg.searxng_url)
        self.queue = HostQueue(cfg.queue_dir)
        self.notifier = Notifier(self.db, self.queue, host_channel=cfg.update_method == "agent")
        self.alerts = AlertManager(self.db, self.notifier)
        self.applier = Applier(cfg, self.db, self.docker, self.sx)
        self.upstream = Upstream(self.db, cfg.image_repo, cfg.github_repo, cfg.github_token)
        self.parser = LogParser()
        self.updater = DockerUpdater(self.docker, self.sx, cfg.container, cfg.update_log_path) if self.docker else None
        self._update_task: asyncio.Task | None = None
        if self.db.kv_get("notify_settings") is None and cfg.notify_host_default:
            save_settings(self.db, {"unraid": True})

        self.container: dict[str, Any] = {}
        self.docker_ok = False
        self.healthy = False
        self.health_failures = 0
        self.runtime_config: dict[str, Any] | None = None
        self.defaults: dict[str, Any] = {"engines": [], "modules": [], "search": {}, "outgoing": {}}
        self._image_id: str | None = None
        self._version: str | None = None
        self._settings_cache: tuple[float, Any] | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._tasks: list[asyncio.Task] = []
        self._probe_now = asyncio.Event()
        self._upstream_now = asyncio.Event()
        self.started = time.time()

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        loops = [self._status_loop, self._metrics_loop, self._probe_loop, self._upstream_loop,
                 self._alerts_loop, self._maintenance_loop]
        if self.docker:
            loops.append(self._logs_loop)
        for fn in loops:
            self._tasks.append(asyncio.create_task(self._guard(fn), name=fn.__name__))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.sx.close()
        await self.notifier.close()
        await self.upstream.close()
        if self.docker:
            await self.docker.close()

    async def _guard(self, fn) -> None:
        while True:
            try:
                await fn()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("collector %s crashed; restarting in 15s", fn.__name__)
                await asyncio.sleep(15)

    # -- pub/sub for the live feed -------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, kind: str, data: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait({"type": kind, **data})
            except asyncio.QueueFull:
                pass

    # -- settings ------------------------------------------------------------
    def settings_data(self):
        """Parsed settings.yml, cached by mtime."""
        path = self.cfg.settings_path
        mtime = path.stat().st_mtime
        if not self._settings_cache or self._settings_cache[0] != mtime:
            self._settings_cache = (mtime, se.load(path.read_text()))
        return self._settings_cache[1]

    def _tokens(self) -> list[str]:
        try:
            return se.engine_tokens(self.settings_data())
        except Exception:
            return []

    def settings_plain(self) -> dict[str, Any]:
        try:
            return se.to_plain(self.settings_data())
        except Exception:
            return {}

    def suspended_times(self) -> dict[str, int]:
        try:
            return se.read_general(self.settings_data(), self.defaults)["suspended_times"]
        except Exception:
            return {}

    def engines(self) -> list[dict[str, Any]]:
        if self.defaults["engines"]:
            return catalog.merge(self.defaults, self.settings_plain(), self.runtime_config)
        # No Docker / catalog yet: fall back to what SearXNG reports.
        return [{**e, "module": None, "loaded": True, "custom": False, "requires_api_key": False, "has_api_key": False,
                 "private": False, "overridden": [], "weight": None, "default_disabled": not e.get("enabled"),
                 "default_inactive": False, "disabled": not e.get("enabled"), "inactive": False, "website": None,
                 "official_api": False} for e in (self.runtime_config or {}).get("engines", [])]

    def web_engines(self, engines: list[dict[str, Any]] | None = None) -> list[str]:
        return [e["name"] for e in (engines or self.engines())
                if e.get("enabled") and analytics.is_web_engine(e["name"], e.get("categories") or [])]

    def running_version(self) -> str | None:
        labels = ((self.container.get("image_labels")) or {})
        return labels.get("org.opencontainers.image.version") or self.container.get("version")

    # -- collectors -------------------------------------------------------
    async def _status_loop(self) -> None:
        while True:
            await self.refresh_status()
            await asyncio.sleep(self.cfg.status_interval)

    async def refresh_status(self) -> None:
        if self.docker:
            try:
                info = await self.docker.inspect(self.cfg.container)
                image_id = info.get("Image")
                img = await self.docker.image(image_id) if image_id else {}
                st = info.get("State") or {}
                self.container = {
                    "name": self.cfg.container, "state": st.get("Status"), "status": st.get("Status"),
                    "running": st.get("Running"), "started_at": st.get("StartedAt"), "restart_count": info.get("RestartCount", 0),
                    "image": (info.get("Config") or {}).get("Image"), "image_id": image_id,
                    "image_created": img.get("Created"), "image_labels": (img.get("Config") or {}).get("Labels") or {},
                }
                self.docker_ok = True
                if image_id and image_id != self._image_id and st.get("Running"):
                    try:
                        self.defaults = await catalog.load_defaults(self.docker, self.cfg.container, image_id, self.cfg.data_dir)
                        if self._image_id is not None:
                            # SearXNG was updated/replaced: refresh "update available" right away.
                            self.request_upstream_check()
                            await self._on_version_change(self._version, self.running_version())
                        self._image_id = image_id
                        self._version = self.running_version()
                    except (DockerError, StopIteration, OSError) as e:
                        log.warning("catalog load failed: %s", e)
            except Exception as e:  # docker unreachable or container missing
                log.warning("docker inspect failed: %s", e)
                self.docker_ok = False
                self.container = {"name": self.cfg.container, "state": "missing", "status": str(e)[:200]}
        self.healthy = await self.sx.healthy()
        self.health_failures = 0 if self.healthy else self.health_failures + 1
        if self.healthy:
            try:
                self.runtime_config = await self.sx.config(self._tokens())
            except Exception as e:
                log.warning("/config failed: %s", e)

    async def _on_version_change(self, old: str | None, new: str | None) -> None:
        if not new or old == new:
            return
        report = self.db.kv_get("upstream_report") or {}
        behind = report.get("image_behind") or {}
        lines = [f"SearXNG: {old or '?'} -> {new}"]
        if report.get("running") == old and (report.get("latest") or {}).get("tag") == new and behind.get("commits"):
            lines.append(f"{behind.get('ahead_by', len(behind['commits']))} upstream commits included.")
            if behind.get("relevant_engines"):
                lines.append("Touches engines you use: " + ", ".join(behind["relevant_engines"]))
            fixes = [c["title"] for c in behind["commits"] if c.get("relevant")][:5]
            lines += [f"- {t}" for t in fixes]
        detail = "\n".join(lines)
        self.db.lifecycle("update", f"{old or '?'} -> {new}")
        self.publish("lifecycle", {"ts": time.time(), "kind": "update", "detail": f"{old} -> {new}"})
        if get_settings(self.db)["notify_updates"]:
            await self.notifier.send("info", f"SearXNG updated to {new}", detail, force=True)

    async def maybe_auto_update(self, snapshot: dict[str, Any]) -> str | None:
        """Queue an update job when policy says so. Returns a reason when queued."""
        s = get_settings(self.db)
        mode = s["auto_update"]
        up = snapshot.get("upstream") or {}
        latest = (up.get("latest") or {}).get("tag")
        if mode == "off" or not up.get("update_available") or not latest:
            return None
        if latest == self.running_version() or self.update_pending():
            return None
        if self.cfg.update_method == "none" or (self.cfg.update_method == "docker" and not self.updater):
            return None
        if self.cfg.update_method == "agent":
            hb = self.queue.agent_heartbeat()
            if hb is None or time.time() - hb > 15 * 60:
                return None  # nobody to run it; the update_stale alert covers this
        attempts = self.db.kv_get("auto_update_attempts", {}) or {}
        if time.time() - attempts.get(latest, 0) < 12 * 3600:
            return None  # already tried this image recently (e.g. it failed and rolled back)

        states = snapshot.get("states") or {}
        relevant = (up.get("image_behind") or {}).get("relevant_engines") or []
        broken = [n for n in relevant if states.get(n, {}).get("status") in ("blocked", "failing", "degraded")]
        reason = None
        if broken:
            reason = f"fix for {', '.join(broken)}"
        elif mode == "always":
            last = float(self.db.kv_get("auto_update_last", 0) or 0)
            pushed = (up.get("latest") or {}).get("pushed")
            try:
                age_h = (time.time() - datetime.fromisoformat(str(pushed).replace("Z", "+00:00")).timestamp()) / 3600
            except ValueError:
                age_h = 99.0
            # Let a burst of upstream builds settle, and don't restart more often than configured.
            if age_h >= 1 and time.time() - last >= float(s["auto_update_min_hours"]) * 3600:
                reason = "new image available"
        if not reason:
            return None
        job = self.request_update(f"auto: {reason}", target=latest)
        attempts[latest] = time.time()
        self.db.kv_set("auto_update_attempts", {k: v for k, v in attempts.items() if time.time() - v < 7 * 86400})
        self.db.kv_set("auto_update_last", time.time())
        self.db.lifecycle("update", f"auto-update queued: {self.running_version()} -> {latest} ({reason}; {job})")
        log.info("auto-update queued (%s)", reason)
        return reason

    async def _metrics_loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self.scrape_metrics()
            except Exception as e:
                log.warning("metrics scrape failed: %s", e)
            await asyncio.sleep(self.cfg.metrics_interval)

    async def scrape_metrics(self) -> None:
        pw = se.metrics_password(self.settings_data())
        if not pw:
            return
        metrics = await self.sx.metrics(pw, self._tokens())
        now = time.time()
        started = self.container.get("started_at") or ""
        base = self.db.kv_get("metrics_baseline", {}) or {}
        prev: dict[str, dict[str, float]] = base.get("counts", {}) if base.get("started_at") == started else {}
        rows = []
        for engine, m in metrics.items():
            p = prev.get(engine, {})
            sent, results = m.get("sent", 0), m.get("results", 0)
            d_sent = sent - p.get("sent", 0) if sent >= p.get("sent", 0) else sent
            d_res = results - p.get("results", 0) if results >= p.get("results", 0) else results
            if d_sent > 0:
                rows.append((now, engine, int(d_sent), int(max(0, d_res)), m.get("total_s"), m.get("http_s")))
        if base.get("started_at") != started and not base:
            rows = []  # very first scrape ever: counts are history we didn't watch accrue
        self.db.executemany("INSERT INTO traffic(ts, engine, sent, results, total_s, http_s) VALUES(?,?,?,?,?,?)", rows)
        self.db.kv_set("metrics_baseline", {"started_at": started, "counts": {
            e: {"sent": m.get("sent", 0), "results": m.get("results", 0)} for e, m in metrics.items()}})
        if rows:
            self.publish("traffic", {"ts": now, "requests": sum(r[2] for r in rows)})

    async def _logs_loop(self) -> None:
        assert self.docker
        while True:
            cursor = float(self.db.kv_get("log_cursor", time.time() - 3600))
            try:
                async for ts, line in self.docker.follow_logs(self.cfg.container, since=cursor - 1):
                    if ts <= cursor:
                        continue
                    self._handle_log(ts, line)
                    cursor = ts
                    self.db.kv_set("log_cursor", cursor)
            except Exception as e:
                log.info("log stream ended (%s); reconnecting", e)
            await asyncio.sleep(3)

    def _handle_log(self, ts: float, line: str) -> None:
        parsed = self.parser.parse(ts, line)
        self.publish("log", {"ts": ts, "line": line[:500]})
        if isinstance(parsed, Startup):
            self.db.lifecycle("start", parsed.version)
            self.publish("lifecycle", {"ts": ts, "kind": "start", "detail": parsed.version})
        elif isinstance(parsed, Event):
            self.db.execute(
                "INSERT INTO events(ts, engine, kind, detail, host, suspended_s, level) VALUES(?,?,?,?,?,?,?)",
                (parsed.ts, parsed.engine, parsed.kind, parsed.detail, parsed.host, parsed.suspended_s, parsed.level))
            self.publish("event", {"ts": parsed.ts, "engine": parsed.engine, "kind": parsed.kind,
                                   "label": KIND_LABELS.get(parsed.kind, parsed.kind), "detail": parsed.detail,
                                   "host": parsed.host})

    async def _probe_loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            last = self.db.one("SELECT ts FROM probes WHERE kind = 'canary' ORDER BY id DESC LIMIT 1")
            interval = int(get_settings(self.db)["probe_interval_min"]) * 60
            due = (last["ts"] + interval) if last else 0
            wait = max(0.0, due - time.time())
            try:
                await asyncio.wait_for(self._probe_now.wait(), timeout=wait if wait > 0 else 0.01)
            except asyncio.TimeoutError:
                pass
            self._probe_now.clear()
            if self.healthy:
                await self.run_canary()
            else:
                await asyncio.sleep(30)

    def request_probe(self) -> None:
        self._probe_now.set()

    async def run_canary(self, query: str | None = None) -> dict[str, Any]:
        q = query or random.choice(CANARY_QUERIES)
        engines = self.engines()
        # Canaries never send the private-engine token, so metered API engines aren't spent on probes.
        general = [e["name"] for e in engines
                   if e.get("enabled") and not e.get("private") and "general" in (e.get("categories") or [])]
        out = await self.sx.search(q, categories="general")
        with_results = out.engines_with_results
        unresp = dict(out.unresponsive)
        pid = self.db.execute(
            "INSERT INTO probes(ts, kind, query, duration_ms, ok, total_results, error) VALUES(?,?,?,?,?,?,?)",
            (time.time(), "canary", q, out.duration_ms, int(out.ok and bool(out.results)), len(out.results), out.error))
        rows = []
        for name in sorted(set(general) | set(with_results) | set(unresp)):
            if name in with_results:
                rows.append((pid, name, "ok", with_results[name], None))
            elif name in unresp:
                rows.append((pid, name, "error", 0, unresp[name]))
            else:
                rows.append((pid, name, "empty", 0, None))
        self.db.executemany("INSERT INTO probe_results(probe_id, engine, status, results, detail) VALUES(?,?,?,?,?)", rows)
        result = self.probe_detail(pid)
        self.publish("probe", {"id": pid, "ok": result["ok"], "ok_engines": result["ok_engines"]})
        return result

    async def test_engine(self, name: str, query: str) -> dict[str, Any]:
        eng = next((e for e in self.engines() if e["name"] == name), None)
        if not eng:
            raise KeyError(name)
        tokens = se.engine_tokens(self.settings_data()) if eng.get("private") else None
        if eng.get("shortcut"):
            out = await self.sx.search(f"!{eng['shortcut']} {query}", tokens=tokens)
        else:
            out = await self.sx.search(query, engines=name, tokens=tokens)
        unresp = dict(out.unresponsive)
        got = out.engines_with_results.get(name, 0)
        status = "ok" if got else ("error" if name in unresp else "empty")
        detail = unresp.get(name) or out.error
        pid = self.db.execute(
            "INSERT INTO probes(ts, kind, query, target, duration_ms, ok, total_results, error) VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), "manual", query, name, out.duration_ms, int(status == "ok"), got, detail))
        self.db.execute("INSERT INTO probe_results(probe_id, engine, status, results, detail) VALUES(?,?,?,?,?)",
                        (pid, name, status, got, detail))
        return {
            "engine": name, "status": status, "detail": detail, "duration_ms": out.duration_ms, "results": got,
            "loaded": eng.get("loaded"),
            "top": [{"title": r.get("title"), "url": r.get("url"), "content": (r.get("content") or "")[:220]}
                    for r in out.results if name in (r.get("engines") or [])][:6],
        }

    def probe_detail(self, pid: int) -> dict[str, Any]:
        p = self.db.one("SELECT * FROM probes WHERE id = ?", (pid,)) or {}
        res = self.db.query("SELECT engine, status, results, detail FROM probe_results WHERE probe_id = ? ORDER BY engine", (pid,))
        web = set(self.web_engines())
        p["results"] = res
        p["ok_engines"] = sum(1 for r in res if r["status"] == "ok" and r["engine"] in web)
        p["web_engines"] = len(web)
        return p

    async def _upstream_loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            last = (self.db.kv_get("upstream_report") or {}).get("checked", 0)
            wait = max(0.0, last + self.cfg.upstream_interval - time.time())
            try:
                await asyncio.wait_for(self._upstream_now.wait(), timeout=wait if wait > 0 else 0.01)
            except asyncio.TimeoutError:
                pass
            self._upstream_now.clear()
            await self.check_upstream()

    async def check_upstream(self) -> dict[str, Any]:
        report = await self.upstream.check(self.running_version(), self.engines())
        self.publish("upstream", {"checked": report["checked"], "update_available": report.get("update_available")})
        return report

    def request_upstream_check(self) -> None:
        self._upstream_now.set()

    async def _alerts_loop(self) -> None:
        await asyncio.sleep(45)
        while True:
            try:
                snap = self.snapshot()
                await self.alerts.sync(snap)
                await self.maybe_auto_update(snap)
            except Exception:
                log.exception("alert evaluation failed")
            await asyncio.sleep(60)

    async def _maintenance_loop(self) -> None:
        while True:
            self.db.prune(self.cfg.retention_days)
            await asyncio.sleep(6 * 3600)

    # -- aggregate views ---------------------------------------------------
    # -- updating SearXNG -------------------------------------------------
    def update_pending(self) -> bool:
        if self.cfg.update_method == "agent":
            return bool(self.queue.pending_jobs("update"))
        return bool(self._update_task and not self._update_task.done())

    def request_update(self, reason: str, target: str | None = None) -> str:
        """Start an update using the configured method. Returns a job/description string."""
        method = self.cfg.update_method
        if method == "agent":
            return self.queue.submit("update", reason=reason, target=target)
        if method != "docker" or not self.updater:
            raise RuntimeError("Updates are disabled (UPDATE_METHOD=none or no Docker access)")
        if self.update_pending():
            return "already running"
        self._update_task = asyncio.create_task(self._run_docker_update(reason))
        return "docker update started"

    async def _run_docker_update(self, reason: str) -> None:
        assert self.updater
        self.publish("lifecycle", {"ts": time.time(), "kind": "update", "detail": f"update started ({reason})"})
        try:
            res = await self.updater.update()
        except Exception as e:  # never leave the task silently dead
            log.exception("update failed")
            from .updater import UpdateResult
            res = UpdateResult(False, f"update crashed: {e}")
        history = self.db.kv_get("update_history", []) or []
        history.insert(0, {"ts": time.time(), "reason": reason, "ok": res.ok, "message": res.message,
                           "rolled_back": res.rolled_back, "from": res.from_version, "to": res.to_version,
                           "log": res.log[-20:]})
        self.db.kv_set("update_history", history[:20])
        if not res.ok:
            self.db.lifecycle("update", f"failed: {res.message}")
            await self.notifier.send("warning", "SearXNG update failed", res.message)
        await self.refresh_status()

    def update_results(self) -> list[dict[str, Any]]:
        if self.cfg.update_method == "agent":
            return [{"ts": None, "finished": r.get("finished"), "ok": r.get("rc") == 0, "message": r.get("output", ""),
                     "reason": (r.get("request") or {}).get("reason")} for r in self.queue.results("update", 5)]
        return (self.db.kv_get("update_history", []) or [])[:5]

    def last_update_log(self, lines: int = 1) -> str:
        p = self.cfg.update_log_path
        try:
            return "\n".join(p.read_text().splitlines()[-lines:])
        except OSError:
            return ""

    def snapshot(self) -> dict[str, Any]:
        engines = self.engines()
        states = analytics.engine_states(self.db, engines, self.suspended_times())
        have_data = bool(self.db.one("SELECT 1 FROM probes WHERE kind='canary' LIMIT 1")) or bool(
            self.db.one("SELECT 1 FROM traffic LIMIT 1"))
        return {
            "container": self.container, "docker_ok": self.docker_ok, "healthy": self.healthy,
            "health_failures": self.health_failures, "states": states, "web_engines": self.web_engines(engines),
            "have_data": have_data, "upstream": self.db.kv_get("upstream_report") or {},
            "last_update_log": self.last_update_log(),
            "agent_heartbeat": self.queue.agent_heartbeat() if self.cfg.update_method == "agent" else None,
            "update_method": self.cfg.update_method,
        }

    def setup_checks(self) -> list[dict[str, str]]:
        """Problems the user should fix, shown on the Overview page."""
        out: list[dict[str, str]] = []
        try:
            data = self.settings_data()
        except FileNotFoundError:
            return [{"id": "settings", "text": f"settings.yml not found at {self.cfg.settings_path} - mount SearXNG's config directory."}]
        except Exception as e:
            return [{"id": "settings", "text": f"settings.yml could not be parsed: {e}"}]
        if not se.metrics_password(data):
            out.append({"id": "metrics", "text": "Set general.open_metrics in settings.yml (any random string) so traffic stats can be collected."})
        if "json" not in (((data.get("search") or {}).get("formats")) or []):
            out.append({"id": "json", "text": "Add json to search.formats in settings.yml - probes and engine tests need it."})
        if self.cfg.enable_docker and not self.docker_ok:
            out.append({"id": "docker", "text": f"Docker not reachable or container '{self.cfg.container}' not found - logs, restarts, updates and the engine catalog are disabled."})
        if not self.healthy:
            out.append({"id": "searxng", "text": f"SearXNG is not answering at {self.cfg.searxng_url}."})
        return out

    def version_info(self) -> dict[str, Any]:
        v = self.running_version()
        return {"version": v, "parsed": parse_version(v), "image": self.container.get("image"),
                "image_created": self.container.get("image_created")}
