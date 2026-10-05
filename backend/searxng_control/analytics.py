"""Read-side computations: engine status, time series, heatmaps."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from .db import DB
from .logparse import BLOCK_KINDS, ERROR_KINDS, KIND_LABELS
from .searxng_client import REFERENCE_ENGINES

DEFAULT_SUSPEND = {"captcha": 1800, "rate_limited": 600, "blocked": 1800, "challenge": 1800}

ERR_KINDS_SQL = "(" + ",".join(f"'{k}'" for k in sorted(ERROR_KINDS)) + ")"
BLOCK_KINDS_SQL = "(" + ",".join(f"'{k}'" for k in sorted(BLOCK_KINDS)) + ")"


def is_web_engine(name: str, categories: list[str]) -> bool:
    return "general" in categories and name not in REFERENCE_ENGINES


def _sum_by_engine(db: DB, table_sql: str, since: float) -> dict[str, int]:
    return {r["engine"]: int(r["n"] or 0) for r in db.query(table_sql, (since,))}


def engine_states(db: DB, engines: list[dict[str, Any]], suspended_times: dict[str, int] | None = None,
                  now: float | None = None) -> dict[str, dict[str, Any]]:
    """Status for every engine in `engines` (rows from catalog.merge or /config)."""
    now = now or time.time()
    susp = dict(DEFAULT_SUSPEND)
    if suspended_times:
        susp.update({
            "captcha": suspended_times.get("SearxEngineCaptcha", susp["captcha"]),
            "rate_limited": suspended_times.get("SearxEngineTooManyRequests", susp["rate_limited"]),
            "blocked": suspended_times.get("SearxEngineAccessDenied", susp["blocked"]),
            "challenge": suspended_times.get("SearxEngineCaptcha", susp["challenge"]),
        })

    h1, h24 = now - 3600, now - 86400
    sent_1h = _sum_by_engine(db, "SELECT engine, SUM(sent) n FROM traffic WHERE ts > ? GROUP BY engine", h1)
    sent_24h = _sum_by_engine(db, "SELECT engine, SUM(sent) n FROM traffic WHERE ts > ? GROUP BY engine", h24)
    err_1h = _sum_by_engine(db, f"SELECT engine, COUNT(*) n FROM events WHERE ts > ? AND kind IN {ERR_KINDS_SQL} GROUP BY engine", h1)
    err_24h = _sum_by_engine(db, f"SELECT engine, COUNT(*) n FROM events WHERE ts > ? AND kind IN {ERR_KINDS_SQL} GROUP BY engine", h24)
    blocks_24h = _sum_by_engine(db, f"SELECT engine, COUNT(*) n FROM events WHERE ts > ? AND kind IN {BLOCK_KINDS_SQL} GROUP BY engine", h24)
    timing = {r["engine"]: r for r in db.query(
        "SELECT engine, AVG(total_s) total_s, AVG(http_s) http_s FROM traffic WHERE ts > ? AND total_s IS NOT NULL GROUP BY engine", (h24,))}

    last_ev: dict[str, dict] = {}
    last_block: dict[str, dict] = {}
    recent_errors = db.query(f"SELECT engine, ts, kind, detail, suspended_s, host FROM events WHERE ts > ? AND kind IN {ERR_KINDS_SQL} "
                             "ORDER BY ts DESC", (now - 7 * 86400,))
    for r in recent_errors:
        e = r["engine"]
        r["label"] = KIND_LABELS.get(r["kind"], r["kind"])
        last_ev.setdefault(e, r)
        if r["kind"] in BLOCK_KINDS:
            last_block.setdefault(e, r)

    # Last time each engine demonstrably worked: a traffic minute with more requests than errors.
    last_ok: dict[str, float] = {}
    err_minutes: dict[tuple[str, int], int] = defaultdict(int)
    for r in db.query(f"SELECT engine, ts FROM events WHERE ts > ? AND kind IN {ERR_KINDS_SQL}", (h24,)):
        err_minutes[(r["engine"], int(r["ts"] // 60))] += 1
    for r in db.query("SELECT engine, ts, sent FROM traffic WHERE ts > ? ORDER BY ts", (h24,)):
        # traffic ts is the scrape time; the requests happened in the minute(s) before it.
        m = int(r["ts"] // 60)
        errs = err_minutes.get((r["engine"], m), 0) + err_minutes.get((r["engine"], m - 1), 0)
        if r["sent"] > errs:
            last_ok[r["engine"]] = r["ts"]

    probe = {}
    last_canary = db.one("SELECT id, ts FROM probes WHERE kind = 'canary' ORDER BY id DESC LIMIT 1")
    if last_canary:
        for r in db.query("SELECT engine, status, results, detail FROM probe_results WHERE probe_id = ?", (last_canary["id"],)):
            probe[r["engine"]] = {**r, "ts": last_canary["ts"]}
            if r["status"] == "ok":
                last_ok[r["engine"]] = max(last_ok.get(r["engine"], 0), last_canary["ts"])
    for r in db.query("SELECT pr.engine, MAX(p.ts) ts FROM probe_results pr JOIN probes p ON p.id = pr.probe_id "
                      "WHERE pr.status = 'ok' AND p.ts > ? GROUP BY pr.engine", (h24,)):
        last_ok[r["engine"]] = max(last_ok.get(r["engine"], 0), r["ts"])

    # Start of the current failure streak: earliest error after the last success.
    failing_since: dict[str, float] = {}
    for r in recent_errors:  # newest first
        e = r["engine"]
        ok_ts = last_ok.get(e)
        if ok_ts and r["ts"] <= ok_ts:
            continue
        failing_since[e] = r["ts"]

    out: dict[str, dict[str, Any]] = {}
    for eng in engines:
        name = eng["name"]
        s1, e1 = sent_1h.get(name, 0), err_1h.get(name, 0)
        s24, e24 = sent_24h.get(name, 0), err_24h.get(name, 0)
        blk = last_block.get(name)
        ok_ts = last_ok.get(name)
        state: dict[str, Any] = {
            "sent_1h": s1, "errors_1h": e1, "sent_24h": s24, "errors_24h": e24, "blocks_24h": blocks_24h.get(name, 0),
            "success_24h": (max(0, s24 - e24) / s24) if s24 else None,
            "median_s": round(timing[name]["total_s"], 2) if name in timing and timing[name]["total_s"] else None,
            "last_error": last_ev.get(name), "last_ok": ok_ts, "probe": probe.get(name), "blocked_until": None,
            "failing_since": failing_since.get(name),
        }
        if not eng.get("enabled"):
            status = "disabled"
        elif blk and (now - blk["ts"]) < (blk["suspended_s"] or susp.get(blk["kind"], 1800)) and (not ok_ts or ok_ts < blk["ts"]):
            status = "blocked"
            state["blocked_until"] = blk["ts"] + (blk["suspended_s"] or susp.get(blk["kind"], 1800))
        elif s1 >= 3:
            rate = max(0, s1 - e1) / s1
            status = "healthy" if rate >= 0.8 else "degraded" if rate >= 0.4 else "failing"
        elif name in probe:
            status = {"ok": "healthy", "error": "failing", "empty": "idle"}.get(probe[name]["status"], "unknown")
            if status == "failing" and probe[name].get("detail") and "suspended" in str(probe[name]["detail"]).lower():
                status = "blocked"
        elif e1 > 0:
            status = "failing"
        elif ok_ts and now - ok_ts < 6 * 3600:
            status = "healthy"
        else:
            status = "unknown"
        state["status"] = status
        out[name] = state
    return out


def hourly_series(db: DB, hours: int = 24, engine: str | None = None, now: float | None = None) -> list[dict[str, Any]]:
    """Per-hour buckets: searches (estimated), engine requests, errors split by blocks vs other."""
    now = now or time.time()
    end = (int(now) // 3600 + 1) * 3600
    start = end - hours * 3600
    eng_sql, params = ("AND engine = ?", (start, engine)) if engine else ("", (start,))
    buckets = {start + i * 3600: {"t": start + i * 3600, "requests": 0, "searches": 0, "blocks": 0, "errors": 0}
               for i in range(hours)}
    per_engine: dict[tuple[int, str], int] = defaultdict(int)
    for r in db.query(f"SELECT ts, engine, sent FROM traffic WHERE ts >= ? {eng_sql}", params):
        b = int(r["ts"] // 3600) * 3600
        if b in buckets:
            buckets[b]["requests"] += r["sent"]
            per_engine[(b, r["engine"])] += r["sent"]
    # A general search hits every enabled engine once, so the busiest engine in a
    # bucket is a decent estimate of the number of searches.
    for (b, _), n in per_engine.items():
        buckets[b]["searches"] = max(buckets[b]["searches"], n)
    for r in db.query(f"SELECT ts, kind FROM events WHERE ts >= ? AND kind IN {ERR_KINDS_SQL} {eng_sql}", params):
        b = int(r["ts"] // 3600) * 3600
        if b in buckets:
            buckets[b]["blocks" if r["kind"] in BLOCK_KINDS else "errors"] += 1
    return list(buckets.values())


def engine_sparks(db: DB, names: list[str], hours: int = 24, now: float | None = None) -> dict[str, list[float | None]]:
    """Success ratio per hour per engine (None = no traffic that hour)."""
    now = now or time.time()
    end = (int(now) // 3600 + 1) * 3600
    start = end - hours * 3600
    sent: dict[tuple[str, int], int] = defaultdict(int)
    errs: dict[tuple[str, int], int] = defaultdict(int)
    for r in db.query("SELECT engine, ts, sent FROM traffic WHERE ts >= ?", (start,)):
        sent[(r["engine"], int((r["ts"] - start) // 3600))] += r["sent"]
    for r in db.query(f"SELECT engine, ts FROM events WHERE ts >= ? AND kind IN {ERR_KINDS_SQL}", (start,)):
        errs[(r["engine"], int((r["ts"] - start) // 3600))] += 1
    out: dict[str, list[float | None]] = {}
    for n in names:
        row: list[float | None] = []
        for i in range(hours):
            s, e = sent.get((n, i), 0), errs.get((n, i), 0)
            if s == 0 and e == 0:
                row.append(None)
            else:
                row.append(max(0.0, (s - e) / s) if s else 0.0)
        out[n] = row
    return out


def heatmap(db: DB, bucket_s: int, buckets: int, kinds: str = "blocks", now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    end = (int(now) // bucket_s + 1) * bucket_s
    start = end - buckets * bucket_s
    kinds_sql = BLOCK_KINDS_SQL if kinds == "blocks" else ERR_KINDS_SQL
    cells: dict[str, list[int]] = {}
    for r in db.query(f"SELECT engine, ts FROM events WHERE ts >= ? AND engine IS NOT NULL AND kind IN {kinds_sql}", (start,)):
        idx = int((r["ts"] - start) // bucket_s)
        if 0 <= idx < buckets:
            cells.setdefault(r["engine"], [0] * buckets)[idx] += 1
    rows = sorted(({"engine": k, "cells": v, "total": sum(v)} for k, v in cells.items()), key=lambda x: -x["total"])
    return {"start": start, "bucket_s": bucket_s, "buckets": buckets, "rows": rows}


def kind_breakdown(db: DB, since: float, engine: str | None = None) -> list[dict[str, Any]]:
    eng_sql, params = ("AND engine = ?", (since, engine)) if engine else ("", (since,))
    return db.query(
        f"SELECT kind, COUNT(*) n, MAX(ts) last FROM events WHERE ts > ? AND kind IN {ERR_KINDS_SQL} {eng_sql} "
        "GROUP BY kind ORDER BY n DESC", params)
