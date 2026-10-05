"""Turn SearXNG container log lines into structured engine events.

SearXNG logs every engine failure, e.g.::

    2026-10-05 12:07:32,326 WARNING:searx.engines.brave: ErrorContext('searx/search/processors/online.py', 207,
        'response = req(...)', 'searx.exceptions.SearxEngineTooManyRequestsException', None,
        ('Too many request (suspended_time=180)',)) False
    2026-10-05 12:07:32,317 WARNING:searx.network.brave: HTTP Request failed: GET https://search.brave.com/search?q=...
    2026-10-05 12:22:47,003 ERROR:searx.engines.privacywall: engine timeout

Only the upstream *host* is kept from URLs - queries never reach the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

LINE_RE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ (?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):(?P<logger>searx[^:]*): (?P<msg>.*)$"
)
EXC_RE = re.compile(r"'((?:[\w]+\.)*\w*(?:Exception|Error))'")
SUSPEND_RE = re.compile(r"suspended_time=(\d+)")
URL_RE = re.compile(r"https?://[^\s'\"]+")
REGISTER_RE = re.compile(r"\(PID \d+\) (?P<engine>.+?): can't register engine")
STARTUP_RE = re.compile(r"^SearXNG (?P<version>\d{4}\.\d+\.\d+[-+][0-9a-f]+)\s*$")

# Kinds that mean "the upstream is refusing us", as opposed to bugs or slowness.
BLOCK_KINDS = frozenset({"captcha", "rate_limited", "blocked", "challenge"})
ERROR_KINDS = BLOCK_KINDS | frozenset(
    {"timeout", "parse_error", "http_error", "network", "ssl", "api_error", "error"}
)

KIND_LABELS = {
    "captcha": "CAPTCHA",
    "rate_limited": "Rate limited (429)",
    "blocked": "Access denied (403)",
    "challenge": "Bot challenge",
    "timeout": "Timeout",
    "parse_error": "Parsing error",
    "http_error": "HTTP error",
    "network": "Network error",
    "ssl": "TLS/SSL error",
    "api_error": "API error",
    "error": "Engine error",
    "load_error": "Failed to load",
    "system": "System",
}


@dataclass
class Event:
    ts: float
    engine: str | None
    kind: str
    detail: str
    host: str | None = None
    suspended_s: int | None = None
    level: str = "WARNING"


@dataclass
class Startup:
    ts: float
    version: str


def _host(text: str) -> str | None:
    m = URL_RE.search(text)
    if not m:
        return None
    try:
        return urlsplit(m.group(0)).hostname
    except ValueError:
        return None


def classify(exc: str, text: str) -> str:
    e = exc.lower()
    t = text.lower()
    if "anubis" in t or "challenge" in t or "cloudflare" in t:
        return "challenge"
    if "captcha" in e or "captcha" in t:
        return "captcha"
    if "toomanyrequests" in e or "too many request" in t or "429" in t:
        return "rate_limited"
    if "accessdenied" in e or "access denied" in t or "http error 403" in t or "http error 402" in t:
        return "blocked"
    if "timeout" in e or "timeout" in t or "timed out" in t:
        return "timeout"
    if "ssl" in e or "ssl" in t or "certificate" in t:
        return "ssl"
    if "apiexception" in e or "api error" in t:
        return "api_error"
    if any(k in e for k in ("jsondecode", "parsererror", "xpath", "keyerror", "indexerror", "attributeerror",
                            "valueerror", "typeerror", "responseexception", "unicode")) or "parsing" in t:
        return "parse_error"
    if "http error" in t or "httperror" in e or "status" in e:
        return "http_error"
    if "connect" in e or "connect" in t or "network" in e or "curl" in e or "dns" in t:
        return "network"
    return "error"


def _error_context_params(msg: str) -> str:
    """The last ErrorContext field is the log_parameters tuple: pull its text out."""
    s = re.sub(r"\s+(?:True|False)\s*$", "", msg.rstrip())
    if s.endswith("))"):
        s = s[:-2]
    idx = s.rfind(", (")
    if idx == -1:
        return msg
    inner = s[idx + 3 :].strip().rstrip(",").strip()
    parts = re.findall(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|([^,]+)""", inner)
    vals = [a or b or c.strip() for a, b, c in parts if (a or b or c.strip())]
    return "; ".join(vals) if vals else inner


def _short(text: str, limit: int = 240) -> str:
    text = URL_RE.sub(lambda m: (urlsplit(m.group(0)).hostname or "url"), text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class LogParser:
    """Stateful: remembers the last upstream host per engine and collapses the
    rare double-report of one failure (e.g. an ErrorContext plus an
    "engine timeout" line for the same engine in the same instant)."""

    DEDUPE_WINDOW = 0.75

    def __init__(self) -> None:
        self._last_host: dict[str, tuple[float, str]] = {}
        self._recent: dict[tuple[str | None, str], float] = {}

    def parse(self, ts: float, line: str) -> Event | Startup | None:
        line = line.rstrip()
        m = STARTUP_RE.match(line)
        if m:
            return Startup(ts, m.group("version"))
        m = LINE_RE.match(line)
        if not m:
            return None
        level, logger, msg = m.group("level"), m.group("logger"), m.group("msg")

        engine: str | None = None
        for prefix in ("searx.engines.", "searx.network."):
            if logger.startswith(prefix):
                engine = logger[len(prefix):]
                break

        if logger.startswith("searx.network.") and engine:
            # Companion line of an engine error: remember the host, don't count it.
            host = _host(msg)
            if host:
                self._last_host[engine] = (ts, host)
            return None

        if logger == "searx.engines":
            reg = REGISTER_RE.search(msg)
            if reg:
                return self._emit(Event(ts, reg.group("engine"), "load_error", _short(msg), level=level))
            return None

        if engine is None:
            # Only keep notable system errors (skip routine noise).
            if level in ("ERROR", "CRITICAL") and "X-Forwarded-For" not in msg:
                return self._emit(Event(ts, None, "system", _short(msg), level=level))
            return None

        if msg.startswith("ErrorContext("):
            exc_m = EXC_RE.search(msg)
            exc = exc_m.group(1).rsplit(".", 1)[-1] if exc_m else ""
            params = _error_context_params(msg)
            kind = classify(exc, params)
            susp = SUSPEND_RE.search(params)
            detail = f"{exc}: {params}" if exc else params
            return self._emit(self._with_host(Event(
                ts, engine, kind, _short(detail), suspended_s=int(susp.group(1)) if susp else None, level=level,
            )))

        if msg.strip() == "engine timeout" or msg.startswith("HTTP requests timeout"):
            return self._emit(self._with_host(Event(ts, engine, "timeout", _short(msg), level=level)))

        if msg.startswith("exception :") or msg.startswith("requests exception") or msg.startswith("HTTP error"):
            kind = classify("", msg)
            return self._emit(self._with_host(Event(ts, engine, kind, _short(msg), level=level)))

        if level in ("ERROR", "CRITICAL"):
            return self._emit(self._with_host(Event(ts, engine, classify("", msg), _short(msg), level=level)))
        return None

    def _with_host(self, ev: Event) -> Event:
        if ev.engine and ev.engine in self._last_host:
            t, host = self._last_host[ev.engine]
            if abs(ev.ts - t) < 5:
                ev.host = host
        return ev

    def _emit(self, ev: Event) -> Event | None:
        key = (ev.engine, ev.kind)
        last = self._recent.get(key)
        self._recent[key] = ev.ts
        if last is not None and abs(ev.ts - last) < self.DEDUPE_WINDOW:
            return None
        if len(self._recent) > 2000:
            cutoff = ev.ts - 60
            self._recent = {k: v for k, v in self._recent.items() if v > cutoff}
        return ev
