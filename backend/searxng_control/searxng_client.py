"""HTTP client for the SearXNG instance (healthz, /config, /metrics, searches)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

METRIC_RE = re.compile(r'^(?P<name>searxng_[a-z_]+)\{engine_name="(?P<engine>(?:[^"\\]|\\.)*)"\}\s+(?P<value>[-0-9.eE+]+)$')

METRIC_KEYS = {
    "searxng_engines_request_count_total": "sent",
    "searxng_engines_result_count_total": "results",
    "searxng_engines_reliability_total": "reliability",
    "searxng_engines_response_time_total_seconds": "total_s",
    "searxng_engines_response_time_http_seconds": "http_s",
    "searxng_engines_response_time_processing_seconds": "processing_s",
}

# Engines that answer side questions (infoboxes, conversions, translations)
# rather than returning web results. Excluded from "web engines" counts.
REFERENCE_ENGINES = frozenset(
    {"wikipedia", "wikidata", "currency", "dictzone", "lingva", "mymemory translated", "ddg definitions",
     "wolframalpha", "wikibooks", "wikiquote", "wikisource", "wikispecies", "wikiversity", "wikivoyage",
     "openlibrary", "tineye", "mozhi", "libretranslate", "deepl", "duden", "wiktionary", "wordnik", "etymonline"}
)


def parse_metrics(text: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        m = METRIC_RE.match(line.strip())
        if not m:
            continue
        key = METRIC_KEYS.get(m.group("name"))
        if not key:
            continue
        engine = m.group("engine").replace('\\"', '"').replace("\\\\", "\\")
        out.setdefault(engine, {})[key] = float(m.group("value"))
    return out


@dataclass
class SearchOutcome:
    ok: bool
    duration_ms: int
    status: int | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    unresponsive: list[tuple[str, str]] = field(default_factory=list)
    answers: list[Any] = field(default_factory=list)
    error: str | None = None

    @property
    def engines_with_results(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            for e in r.get("engines") or [r.get("engine")]:
                if e:
                    counts[e] = counts.get(e, 0) + 1
        return counts


class SearXNG:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30, headers={
            # Bot detection logs a warning without these; tailscale serve sets them for real users.
            "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1", "User-Agent": "searxng-control",
        })

    async def close(self) -> None:
        await self._client.aclose()

    async def healthy(self) -> bool:
        try:
            r = await self._client.get("/healthz", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _tok(tokens: list[str] | None) -> dict[str, str] | None:
        # Private (token-gated) engines are hidden from /config, /metrics and /stats
        # unless the request carries their token, exactly like a browser would.
        return {"tokens": ",".join(tokens)} if tokens else None

    async def config(self, tokens: list[str] | None = None) -> dict:
        r = await self._client.get("/config", cookies=self._tok(tokens), timeout=10)
        r.raise_for_status()
        return r.json()

    async def stats_errors(self, tokens: list[str] | None = None) -> dict:
        r = await self._client.get("/stats/errors", cookies=self._tok(tokens), timeout=10)
        r.raise_for_status()
        return r.json()

    async def metrics(self, password: str, tokens: list[str] | None = None) -> dict[str, dict[str, float]]:
        r = await self._client.get("/metrics", auth=("dashboard", password), cookies=self._tok(tokens), timeout=10)
        r.raise_for_status()
        return parse_metrics(r.text)

    async def search(self, q: str, *, categories: str | None = None, engines: str | None = None,
                     tokens: list[str] | None = None, timeout: float = 30) -> SearchOutcome:
        params: dict[str, str] = {"q": q, "format": "json"}
        if categories:
            params["categories"] = categories
        if engines:
            params["engines"] = engines
        cookies = self._tok(tokens)
        t0 = time.perf_counter()
        try:
            r = await self._client.get("/search", params=params, cookies=cookies, timeout=timeout)
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                return SearchOutcome(False, ms, r.status_code, error=f"HTTP {r.status_code}")
            data = r.json()
            return SearchOutcome(
                ok=True, duration_ms=ms, status=200,
                results=data.get("results") or [],
                unresponsive=[(u[0], u[1]) for u in data.get("unresponsive_engines") or [] if len(u) >= 2],
                answers=data.get("answers") or [],
            )
        except (httpx.HTTPError, ValueError) as e:
            return SearchOutcome(False, int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
