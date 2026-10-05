"""Alert rules. Each rule yields (key, severity, title, detail) while its
condition holds; the engine opens/resolves alerts and notifies on transitions."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .db import DB
from .notify import Notifier, get_settings


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (time.time() - datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) / 3600
    except ValueError:
        return None


def evaluate(snapshot: dict[str, Any], settings: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Pure function: current state -> active alert conditions."""
    out: list[tuple[str, str, str, str]] = []
    now = time.time()
    container = snapshot.get("container") or {}
    if snapshot.get("docker_ok") and container and container.get("state") != "running":
        out.append(("container_down", "critical", "SearXNG container is not running",
                    f"State: {container.get('state')} ({container.get('status', '')})"))
    elif snapshot.get("health_failures", 0) >= 2:
        out.append(("searxng_unhealthy", "critical", "SearXNG is not answering",
                    f"/healthz failed {snapshot['health_failures']} checks in a row"))

    states: dict[str, dict] = snapshot.get("states") or {}
    web = snapshot.get("web_engines") or []
    working = [n for n in web if states.get(n, {}).get("status") in ("healthy", "degraded")]
    if web and snapshot.get("have_data") and len(working) < int(settings["min_web_engines"]):
        down = [f"{n} ({states.get(n, {}).get('status', '?')})" for n in web if n not in working]
        out.append(("web_engines_low", "warning", f"Only {len(working)} of {len(web)} web engines working",
                    "Not working: " + ", ".join(down)))

    blocked_h = float(settings["engine_blocked_hours"])
    for n in web:
        st = states.get(n) or {}
        since = st.get("failing_since")
        if st.get("status") in ("blocked", "failing") and since and now - since >= blocked_h * 3600:
            err = st.get("last_error") or {}
            out.append((f"engine_down:{n}", "warning", f"{n} has been {st['status']} for {(now - since) / 3600:.0f}h",
                        f"Last error: {err.get('label') or err.get('kind', '?')} - {err.get('detail', '')}"[:400]))

    up = snapshot.get("upstream") or {}
    behind = up.get("image_behind") or {}
    latest = up.get("latest") or {}
    if up.get("update_available"):
        age = _age_hours(latest.get("pushed"))
        broken = [n for n in behind.get("relevant_engines", []) if states.get(n, {}).get("status") in ("blocked", "failing", "degraded")]
        if broken:
            out.append(("fix_available", "warning", f"Upstream fix available for {', '.join(broken)}",
                        f"Image {latest.get('tag')} contains changes to engines that are failing here. Update SearXNG."))
        elif age is not None and age >= float(settings["update_stale_hours"]) + (
                float(settings.get("auto_update_min_hours", 0)) if settings.get("auto_update") == "always" else 0):
            out.append(("update_stale", "warning", "SearXNG update pending",
                        f"{latest.get('tag')} was published {age:.0f}h ago and SearXNG still runs {up.get('running')}. "
                        f"{behind.get('ahead_by', 0)} commits behind ({behind.get('relevant_count', 0)} touch your engines). "
                        "Check the searxng-update user script."))

    upd = snapshot.get("last_update_log") or ""
    if "unhealthy" in upd or "rolling back" in upd:
        out.append(("update_failed", "warning", "Last SearXNG auto-update failed", upd[-400:]))

    hb = snapshot.get("agent_heartbeat")
    if hb is not None and now - hb > 15 * 60:
        out.append(("agent_stale", "info", "Host agent not running",
                    "The host agent hasn't checked in for 15+ minutes; queued updates and host notifications are paused."))
    return out


class AlertManager:
    def __init__(self, db: DB, notifier: Notifier):
        self.db, self.notifier = db, notifier

    def active(self) -> list[dict]:
        return self.db.query("SELECT * FROM alerts WHERE resolved IS NULL ORDER BY opened DESC")

    def history(self, limit: int = 100) -> list[dict]:
        return self.db.query("SELECT * FROM alerts ORDER BY opened DESC LIMIT ?", (limit,))

    async def sync(self, snapshot: dict[str, Any]) -> None:
        settings = get_settings(self.db)
        conditions = {key: (sev, title, detail) for key, sev, title, detail in evaluate(snapshot, settings)}
        open_rows = {r["key"]: r for r in self.active()}
        now = time.time()
        for key, (sev, title, detail) in conditions.items():
            if key in open_rows:
                row = open_rows[key]
                if row["title"] != title or row["detail"] != detail:
                    self.db.execute("UPDATE alerts SET title = ?, detail = ?, severity = ? WHERE id = ?", (title, detail, sev, row["id"]))
                continue
            aid = self.db.execute("INSERT INTO alerts(key, severity, title, detail, opened) VALUES(?,?,?,?,?)",
                                  (key, sev, title, detail, now))
            sent = await self.notifier.send(sev, f"SearXNG: {title}", detail)
            if sent:
                self.db.execute("UPDATE alerts SET notified = 1 WHERE id = ?", (aid,))
        for key, row in open_rows.items():
            if key not in conditions:
                self.db.execute("UPDATE alerts SET resolved = ? WHERE id = ?", (now, row["id"]))
                if row["notified"]:
                    await self.notifier.send(row["severity"], f"SearXNG resolved: {row['title']}",
                                             "This condition has cleared.", resolved=True)
