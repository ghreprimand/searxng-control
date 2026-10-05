"""REST + SSE API consumed by the frontend. All routes live under /api."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import analytics, settings_editor as se
from .applier import settings_file_info
from .hub import Hub
from .logparse import KIND_LABELS
from .notify import get_settings, save_settings


def _apply_payload(res) -> dict[str, Any]:
    return {"ok": res.ok, "message": res.message, "rolled_back": res.rolled_back, "backup": res.backup,
            "log_tail": res.log_tail, "duration_s": round(res.duration_s, 1)}


class ConfigPatch(BaseModel):
    engines: dict[str, dict[str, Any]] = {}
    general: dict[str, Any] = {}
    hostnames: dict[str, Any] | None = None
    add_engine: str | None = None
    remove_engine: str | None = None
    note: str | None = None


class RawSettings(BaseModel):
    text: str
    note: str | None = None


class TestRequest(BaseModel):
    query: str = "open source search engine"


class ProbeRequest(BaseModel):
    query: str | None = None


def build_router(hub: Hub) -> APIRouter:
    r = APIRouter(prefix="/api")

    def engine_defaults() -> dict[str, dict[str, Any]]:
        return {e["name"]: e for e in hub.defaults.get("engines", [])}

    def private_token() -> str:
        tok = hub.db.kv_get("private_engine_token")
        existing = se.engine_tokens(hub.settings_data())
        if existing:
            tok = existing[0]
        if not tok:
            tok = secrets.token_hex(8)
        hub.db.kv_set("private_engine_token", tok)
        return tok

    def build_new_text(patch: ConfigPatch) -> tuple[str, str]:
        current = hub.applier.read()
        data = se.load(current)
        defaults = engine_defaults()
        summary: list[str] = []
        for name, p in patch.engines.items():
            if name not in defaults and not any(e["name"] == name for e in hub.engines()):
                raise se.SettingsError(f"unknown engine {name}")
            se.patch_engine(data, name, p, defaults.get(name), token=private_token() if p.get("private") else None)
            summary.append(f"{name}: " + ", ".join(f"{k}={'***' if k == 'api_key' and v else v}" for k, v in p.items()))
        if patch.general:
            se.patch_general(data, patch.general)
            summary.append("general: " + ", ".join(patch.general))
        if patch.hostnames is not None:
            se.patch_hostnames(data, patch.hostnames)
            summary.append("site rules")
        if patch.add_engine:
            name = se.add_custom_engine(data, patch.add_engine, hub.defaults.get("modules", []),
                                        {e["name"] for e in hub.engines()})
            summary.append(f"added engine {name}")
        if patch.remove_engine:
            se.remove_custom_engine(data, patch.remove_engine, set(defaults))
            summary.append(f"removed engine {patch.remove_engine}")
        note = patch.note or "; ".join(summary) or "dashboard edit"
        return se.dump(data), note

    # -- overview -------------------------------------------------------------
    @r.get("/overview")
    async def overview() -> dict[str, Any]:
        engines = hub.engines()
        states = analytics.engine_states(hub.db, engines, hub.suspended_times())
        web = hub.web_engines(engines)
        enabled = [e for e in engines if e.get("enabled")]
        sparks = analytics.engine_sparks(hub.db, [e["name"] for e in enabled])
        series = analytics.hourly_series(hub.db, 24)
        now = time.time()
        last_probe = hub.db.one("SELECT id FROM probes WHERE kind='canary' ORDER BY id DESC LIMIT 1")
        rows = []
        for e in enabled:
            st = states[e["name"]]
            rows.append({**{k: e[k] for k in ("name", "shortcut", "categories", "private", "module")},
                         **st, "web": e["name"] in web, "spark": sparks.get(e["name"])})
        order = {"blocked": 0, "failing": 1, "degraded": 2, "unknown": 3, "idle": 4, "healthy": 5}
        rows.sort(key=lambda x: (not x["web"], order.get(x["status"], 9), x["name"]))
        working = [n for n in web if states[n]["status"] in ("healthy", "degraded")]
        latency = [states[n]["median_s"] for n in web if states[n]["median_s"]]
        upstream = hub.db.kv_get("upstream_report") or {}
        return {
            "now": now,
            "searxng": {**hub.version_info(), "container": hub.container, "healthy": hub.healthy,
                        "docker_ok": hub.docker_ok, "public_url": hub.cfg.link_url},
            "summary": {
                "web_total": len(web), "web_working": len(working),
                "searches_24h": sum(b["searches"] for b in series), "requests_24h": sum(b["requests"] for b in series),
                "blocks_24h": sum(b["blocks"] for b in series), "errors_24h": sum(b["errors"] for b in series),
                "median_latency_s": round(sorted(latency)[len(latency) // 2], 2) if latency else None,
                "engines_enabled": len(enabled),
            },
            "engines": rows,
            "series": series,
            "last_probe": hub.probe_detail(last_probe["id"]) if last_probe else None,
            "alerts": hub.alerts.active(),
            "setup": hub.setup_checks(),
            "update": {"available": upstream.get("update_available"), "latest": (upstream.get("latest") or {}).get("tag"),
                       "behind": (upstream.get("image_behind") or {}).get("ahead_by", 0),
                       "relevant": (upstream.get("image_behind") or {}).get("relevant_count", 0)},
            "recent_events": [{**ev, "label": KIND_LABELS.get(ev["kind"], ev["kind"])} for ev in hub.db.query(
                "SELECT ts, engine, kind, detail, host FROM events WHERE engine IS NOT NULL ORDER BY ts DESC LIMIT 12")],
        }

    # -- engines --------------------------------------------------------------
    @r.get("/engines")
    async def engines() -> dict[str, Any]:
        rows = hub.engines()
        states = analytics.engine_states(hub.db, rows, hub.suspended_times())
        web = set(hub.web_engines(rows))
        return {"engines": [{**e, **states[e["name"]], "web": e["name"] in web} for e in rows],
                "catalog_loaded": bool(hub.defaults.get("engines")),
                "private_token": se.engine_tokens(hub.settings_data())[:1] or None,
                "public_url": hub.cfg.link_url}

    @r.get("/engines/{name}")
    async def engine_detail(name: str) -> dict[str, Any]:
        rows = hub.engines()
        eng = next((e for e in rows if e["name"] == name), None)
        if not eng:
            raise HTTPException(404, "unknown engine")
        state = analytics.engine_states(hub.db, [eng], hub.suspended_times())[name]
        now = time.time()
        user_entry = next((e for e in se.to_plain(hub.settings_data()).get("engines") or [] if e.get("name") == name), None)
        if user_entry and "api_key" in user_entry:
            user_entry = {**user_entry, "api_key": "•••• (set)"}
        default_entry = next((e for e in hub.defaults.get("engines", []) if e["name"] == name), None)
        return {
            "engine": {**eng, **state},
            "series": analytics.hourly_series(hub.db, 48, engine=name),
            "kinds_7d": [{**k, "label": KIND_LABELS.get(k["kind"], k["kind"])} for k in analytics.kind_breakdown(hub.db, now - 7 * 86400, name)],
            "events": [{**ev, "label": KIND_LABELS.get(ev["kind"], ev["kind"])} for ev in hub.db.query(
                "SELECT ts, kind, detail, host, suspended_s FROM events WHERE engine = ? ORDER BY ts DESC LIMIT 60", (name,))],
            "probes": hub.db.query(
                "SELECT p.ts, p.kind, p.query, pr.status, pr.results, pr.detail FROM probe_results pr "
                "JOIN probes p ON p.id = pr.probe_id WHERE pr.engine = ? ORDER BY p.ts DESC LIMIT 30", (name,)),
            "settings_entry": user_entry, "default_entry": default_entry,
            "private_token": (se.engine_tokens(hub.settings_data()) or [None])[0] if eng.get("private") else None,
            "public_url": hub.cfg.link_url,
        }

    @r.post("/engines/{name}/test")
    async def engine_test(name: str, body: TestRequest) -> dict[str, Any]:
        try:
            return await hub.test_engine(name, body.query.strip() or "open source search engine")
        except KeyError:
            raise HTTPException(404, "unknown engine")

    # -- activity ---------------------------------------------------------------
    @r.get("/events")
    async def events(engine: str | None = None, kind: str | None = None, limit: int = 200, before: float | None = None) -> dict[str, Any]:
        where, params = ["1=1"], []
        if engine:
            where.append("engine = ?")
            params.append(engine)
        if kind == "blocks":
            where.append("kind IN ('captcha','rate_limited','blocked','challenge')")
        elif kind:
            where.append("kind = ?")
            params.append(kind)
        if before:
            where.append("ts < ?")
            params.append(before)
        rows = hub.db.query(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?",
                            (*params, min(limit, 1000)))
        return {"events": [{**e, "label": KIND_LABELS.get(e["kind"], e["kind"])} for e in rows], "labels": KIND_LABELS}

    @r.get("/activity")
    async def activity(range: str = "48h") -> dict[str, Any]:
        now = time.time()
        if range == "30d":
            hm, series, since = analytics.heatmap(hub.db, 86400, 30), analytics.hourly_series(hub.db, 24 * 7), now - 30 * 86400
        elif range == "7d":
            hm, series, since = analytics.heatmap(hub.db, 6 * 3600, 28), analytics.hourly_series(hub.db, 24 * 7), now - 7 * 86400
        else:
            hm, series, since = analytics.heatmap(hub.db, 3600, 48), analytics.hourly_series(hub.db, 48), now - 48 * 3600
        by_engine = hub.db.query(
            "SELECT engine, kind, COUNT(*) n FROM events WHERE ts > ? AND engine IS NOT NULL GROUP BY engine, kind", (since,))
        lifecycle = hub.db.query("SELECT * FROM lifecycle WHERE ts > ? ORDER BY ts DESC LIMIT 50", (since,))
        return {"heatmap": hm, "series": series, "kinds": [{**k, "label": KIND_LABELS.get(k["kind"], k["kind"])}
                                                          for k in analytics.kind_breakdown(hub.db, since)],
                "by_engine": by_engine, "lifecycle": lifecycle, "labels": KIND_LABELS}

    @r.get("/logs")
    async def logs(lines: int = 300) -> dict[str, Any]:
        if not hub.docker:
            return {"lines": []}
        tail = await hub.docker.logs_tail(hub.cfg.container, min(lines, 2000))
        return {"lines": [{"ts": ts, "line": line} for ts, line in tail]}

    @r.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        q = hub.subscribe()

        async def gen():
            try:
                yield "retry: 3000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=20)
                        yield f"data: {json.dumps(msg)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # -- probes -----------------------------------------------------------------
    @r.get("/probes")
    async def probes(limit: int = 50) -> dict[str, Any]:
        rows = hub.db.query("SELECT * FROM probes ORDER BY id DESC LIMIT ?", (min(limit, 500),))
        ids = [p["id"] for p in rows]
        results: dict[int, list] = {}
        if ids:
            for pr in hub.db.query(f"SELECT * FROM probe_results WHERE probe_id IN ({','.join('?' * len(ids))})", tuple(ids)):
                results.setdefault(pr["probe_id"], []).append(pr)
        web = set(hub.web_engines())
        for p in rows:
            p["results"] = sorted(results.get(p["id"], []), key=lambda x: x["engine"])
            p["ok_engines"] = sum(1 for x in p["results"] if x["status"] == "ok" and x["engine"] in web)
        s = get_settings(hub.db)
        return {"probes": rows, "interval_min": s["probe_interval_min"], "web_engines": sorted(web)}

    @r.post("/probes/run")
    async def probe_run(body: ProbeRequest) -> dict[str, Any]:
        return await hub.run_canary(body.query or None)

    # -- configuration ------------------------------------------------------------
    @r.get("/config")
    async def config_get() -> dict[str, Any]:
        data = hub.settings_data()
        plain = se.to_plain(data)
        return {
            "general": se.read_general(data, hub.defaults),
            "hostnames": se.read_hostnames(data),
            "file": settings_file_info(hub.cfg.settings_path),
            "modules": hub.defaults.get("modules", []),
            "custom_engines": [e for e in plain.get("engines") or [] if e.get("name") not in {d["name"] for d in hub.defaults.get("engines", [])}],
            "private_token": (se.engine_tokens(data) or [None])[0],
            "options": {
                "autocomplete": ["", "360search", "baidu", "bing", "brave", "dbpedia", "duckduckgo", "google", "kagi", "mwmbl",
                                 "naver", "privacywall", "quark", "qwant", "seznam", "sogou", "startpage", "swisscows", "wikipedia", "yandex"],
                "favicon_resolver": ["", "allesedv", "duckduckgo", "google", "kagi", "yandex"],
                "safe_search": [0, 1, 2],
            },
        }

    @r.post("/config/preview")
    async def config_preview(patch: ConfigPatch) -> dict[str, Any]:
        try:
            new, note = build_new_text(patch)
            se.validate(new)
        except se.SettingsError as e:
            raise HTTPException(400, str(e))
        return {"diff": se.diff(hub.applier.read(), new), "note": note}

    @r.post("/config/apply")
    async def config_apply(patch: ConfigPatch) -> dict[str, Any]:
        try:
            new, note = build_new_text(patch)
            res = await hub.applier.apply(new, note)
        except se.SettingsError as e:
            raise HTTPException(400, str(e))
        await hub.refresh_status()
        return _apply_payload(res)

    @r.get("/config/raw")
    async def raw_get() -> dict[str, Any]:
        return {"text": hub.applier.read(), "file": settings_file_info(hub.cfg.settings_path)}

    @r.post("/config/raw/preview")
    async def raw_preview(body: RawSettings) -> dict[str, Any]:
        try:
            se.validate(body.text)
        except se.SettingsError as e:
            raise HTTPException(400, str(e))
        return {"diff": se.diff(hub.applier.read(), body.text)}

    @r.put("/config/raw")
    async def raw_put(body: RawSettings) -> dict[str, Any]:
        try:
            res = await hub.applier.apply(body.text, body.note or "raw edit")
        except se.SettingsError as e:
            raise HTTPException(400, str(e))
        await hub.refresh_status()
        return _apply_payload(res)

    @r.get("/backups")
    async def backups() -> dict[str, Any]:
        return {"backups": hub.applier.list_backups()}

    @r.get("/backups/{name}")
    async def backup_get(name: str) -> dict[str, Any]:
        try:
            text = hub.applier.read_backup(name)
        except FileNotFoundError:
            raise HTTPException(404, "no such backup")
        return {"name": name, "text": text, "diff": se.diff(hub.applier.read(), text)}

    @r.post("/backups/{name}/restore")
    async def backup_restore(name: str) -> dict[str, Any]:
        try:
            res = await hub.applier.restore(name)
        except FileNotFoundError:
            raise HTTPException(404, "no such backup")
        except se.SettingsError as e:
            raise HTTPException(400, str(e))
        await hub.refresh_status()
        return _apply_payload(res)

    @r.post("/searxng/restart")
    async def restart() -> dict[str, Any]:
        res = await hub.applier.restart_only()
        await hub.refresh_status()
        return _apply_payload(res)

    # -- updates -------------------------------------------------------------------
    @r.get("/updates")
    async def updates() -> dict[str, Any]:
        report = hub.db.kv_get("upstream_report") or {}
        try:
            log_lines = hub.cfg.update_log_path.read_text().splitlines()[-40:]
        except OSError:
            log_lines = []
        return {"running": hub.version_info(), "report": report, "update_log": log_lines,
                "method": hub.cfg.update_method, "pending": hub.update_pending(), "results": hub.update_results(),
                "agent_heartbeat": hub.queue.agent_heartbeat() if hub.cfg.update_method == "agent" else None,
                "auto": {k: get_settings(hub.db)[k] for k in ("auto_update", "auto_update_min_hours", "notify_updates")},
                "auto_last": hub.db.kv_get("auto_update_last"),
                "lifecycle": hub.db.query("SELECT * FROM lifecycle WHERE kind IN ('start','update') ORDER BY ts DESC LIMIT 20")}

    @r.post("/updates/check")
    async def updates_check() -> dict[str, Any]:
        return await hub.check_upstream()

    @r.post("/updates/apply")
    async def updates_apply() -> dict[str, Any]:
        if hub.update_pending():
            return {"queued": False, "message": "An update is already in progress"}
        try:
            job = hub.request_update("requested from dashboard")
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        hub.db.lifecycle("update", f"requested from dashboard ({job})")
        msg = ("Queued - the host agent picks it up within a minute" if hub.cfg.update_method == "agent"
               else "Updating now - pulling the image and recreating the container")
        return {"queued": True, "job": job, "message": msg}

    # -- alerts & notifications -------------------------------------------------
    @r.get("/alerts")
    async def alerts() -> dict[str, Any]:
        return {"active": hub.alerts.active(), "history": hub.alerts.history(100),
                "settings": get_settings(hub.db), "update_method": hub.cfg.update_method,
                "agent_heartbeat": hub.queue.agent_heartbeat() if hub.cfg.update_method == "agent" else None}

    @r.put("/alerts/settings")
    async def alerts_settings(body: dict[str, Any]) -> dict[str, Any]:
        return save_settings(hub.db, body)

    @r.post("/alerts/test")
    async def alerts_test() -> dict[str, Any]:
        sent = await hub.notifier.send("warning", "SearXNG dashboard test", "If you can read this, notifications work.", force=True)
        return {"sent": sent}

    @r.get("/meta")
    async def meta(request: Request) -> dict[str, Any]:
        return {"user": request.headers.get("Tailscale-User-Login") or request.headers.get("Remote-User"),
                "name": request.headers.get("Tailscale-User-Name"), "public_url": hub.cfg.link_url,
                "label": hub.cfg.instance_label, "update_method": hub.cfg.update_method, "started": hub.started}

    return r
