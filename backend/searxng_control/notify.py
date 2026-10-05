"""Notification channels: ntfy, and host-agent notifications (e.g. Unraid's notify) in agent mode."""

from __future__ import annotations

import logging

import httpx

from .db import DB
from .hostqueue import HostQueue

log = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "unraid": False,           # host-agent notification (Unraid notify); agent update mode only
    "ntfy_url": "",            # e.g. https://ntfy.sh/my-topic or http://host:port/topic
    "ntfy_token": "",
    "min_severity": "warning", # info | warning | critical
    "notify_resolved": True,
    # Alert thresholds (used by alerts.py)
    "min_web_engines": 3,
    "engine_blocked_hours": 2.0,
    "update_stale_hours": 36.0,
    "probe_interval_min": 30,
    # Updates: "always" = install new SearXNG images automatically (at most every
    # auto_update_min_hours, immediately when they fix an engine that's failing here),
    # "fixes" = only those urgent ones, "off" = only the nightly user script.
    "auto_update": "always",
    "auto_update_min_hours": 6.0,
    "notify_updates": True,     # notify whenever SearXNG changes version
}

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
UNRAID_IMPORTANCE = {"info": "normal", "warning": "warning", "critical": "alert"}
NTFY_PRIORITY = {"info": "default", "warning": "high", "critical": "urgent"}


def get_settings(db: DB) -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(db.kv_get("notify_settings", {}) or {})
    return s


def save_settings(db: DB, patch: dict) -> dict:
    s = get_settings(db)
    for k, v in patch.items():
        if k in DEFAULT_SETTINGS:
            s[k] = type(DEFAULT_SETTINGS[k])(v) if not isinstance(DEFAULT_SETTINGS[k], bool) else bool(v)
    s["probe_interval_min"] = max(5, int(s["probe_interval_min"]))
    if s["auto_update"] not in ("always", "fixes", "off"):
        s["auto_update"] = "always"
    s["auto_update_min_hours"] = max(1.0, float(s["auto_update_min_hours"]))
    db.kv_set("notify_settings", s)
    return s


class Notifier:
    def __init__(self, db: DB, queue: HostQueue, host_channel: bool = False):
        self.db, self.queue = db, queue
        self.host_channel = host_channel  # only in agent mode is anyone reading the queue
        self._http = httpx.AsyncClient(timeout=10)

    async def close(self) -> None:
        await self._http.aclose()

    async def send(self, severity: str, title: str, body: str, *, force: bool = False, resolved: bool = False) -> list[str]:
        s = get_settings(self.db)
        if not force and SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK.get(s["min_severity"], 1):
            return []
        if resolved and not s["notify_resolved"] and not force:
            return []
        sent: list[str] = []
        if s["unraid"] and self.host_channel:
            self.queue.submit("notify", subject=title, description=body,
                              importance="normal" if resolved else UNRAID_IMPORTANCE.get(severity, "normal"))
            sent.append("unraid")
        if s["ntfy_url"]:
            headers = {"Title": title.encode("utf-8"), "Priority": "default" if resolved else NTFY_PRIORITY.get(severity, "default"),
                       "Tags": "white_check_mark" if resolved else ("rotating_light" if severity == "critical" else "warning")}
            if s["ntfy_token"]:
                headers["Authorization"] = f"Bearer {s['ntfy_token']}"
            try:
                r = await self._http.post(s["ntfy_url"], content=body.encode("utf-8"), headers=headers)
                r.raise_for_status()
                sent.append("ntfy")
            except httpx.HTTPError as e:
                log.warning("ntfy failed: %s", e)
        return sent
