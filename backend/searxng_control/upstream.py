"""Track upstream SearXNG: newest Docker image vs. what is running, and which
commits in between touch the engines you actually use."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from .db import DB

log = logging.getLogger(__name__)

VERSION_RE = re.compile(r"^(?P<date>\d{4}\.\d{1,2}\.\d{1,2})[-+](?P<commit>[0-9a-f]{7,40})$")
HUB_TAGS = "https://hub.docker.com/v2/repositories/{repo}/tags?page_size=50&ordering=last_updated"
MAX_COMMIT_DETAILS = 40


def parse_version(v: str | None) -> dict[str, str] | None:
    if not v:
        return None
    m = VERSION_RE.match(v.strip())
    return m.groupdict() if m else None


class Upstream:
    def __init__(self, db: DB, image_repo: str, github_repo: str, github_token: str = ""):
        self.db = db
        self.image_repo = image_repo
        self.github_repo = github_repo
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "searxng-control"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        self._gh = httpx.AsyncClient(base_url="https://api.github.com", headers=headers, timeout=20)
        self._hub = httpx.AsyncClient(timeout=20, headers={"User-Agent": "searxng-control"})

    async def close(self) -> None:
        await self._gh.aclose()
        await self._hub.aclose()

    async def latest_image(self) -> dict[str, Any] | None:
        r = await self._hub.get(HUB_TAGS.format(repo=self.image_repo))
        r.raise_for_status()
        tags = r.json().get("results") or []
        versioned = [t for t in tags if parse_version(t.get("name"))]
        if not versioned:
            return None
        newest = max(versioned, key=lambda t: t.get("last_updated") or "")
        latest_digest = next((t.get("digest") for t in tags if t.get("name") == "latest"), None)
        return {
            "tag": newest["name"], "pushed": newest.get("last_updated"), "digest": newest.get("digest"),
            "latest_digest": latest_digest, "recent_tags": [t["name"] for t in versioned[:10]],
        }

    async def _commit_files(self, sha: str) -> list[str]:
        cache = self.db.kv_get(f"gh_commit:{sha}")
        if cache is not None:
            return cache
        r = await self._gh.get(f"/repos/{self.github_repo}/commits/{sha}")
        if r.status_code != 200:
            return []
        files = [f["filename"] for f in r.json().get("files") or []]
        self.db.kv_set(f"gh_commit:{sha}", files)
        return files

    async def compare(self, base: str, head: str) -> dict[str, Any]:
        r = await self._gh.get(f"/repos/{self.github_repo}/compare/{base}...{head}")
        if r.status_code != 200:
            return {"error": f"GitHub compare {r.status_code}", "commits": [], "ahead_by": 0}
        data = r.json()
        commits = []
        for c in data.get("commits") or []:
            msg = (c.get("commit") or {}).get("message", "")
            commits.append({
                "sha": c["sha"], "short": c["sha"][:9], "title": msg.split("\n", 1)[0], "body": msg[:2000],
                "date": ((c.get("commit") or {}).get("committer") or {}).get("date"),
                "author": ((c.get("commit") or {}).get("author") or {}).get("name"), "url": c.get("html_url"),
            })
        commits.reverse()  # newest first
        for c in commits[:MAX_COMMIT_DETAILS]:
            c["files"] = await self._commit_files(c["sha"])
        return {"ahead_by": data.get("ahead_by", len(commits)), "commits": commits,
                "files": [f["filename"] for f in data.get("files") or []]}

    async def check(self, running_version: str | None, engines: list[dict[str, Any]]) -> dict[str, Any]:
        """Return and cache the full upstream report."""
        report: dict[str, Any] = {"checked": time.time(), "running": running_version, "error": None}
        try:
            latest = await self.latest_image()
            report["latest"] = latest
            run = parse_version(running_version)
            lat = parse_version(latest["tag"]) if latest else None
            report["update_available"] = bool(run and lat and run["commit"] != lat["commit"])
            report["image_behind"] = await self.compare(run["commit"], lat["commit"]) if report["update_available"] else {"ahead_by": 0, "commits": []}
            report["upcoming"] = await self.compare(lat["commit"], "master") if lat else {"ahead_by": 0, "commits": []}
        except httpx.HTTPError as e:
            report["error"] = f"{type(e).__name__}: {e}"
            log.warning("upstream check failed: %s", e)
        annotate_relevance(report, engines)
        self.db.kv_set("upstream_report", report)
        return report


def annotate_relevance(report: dict[str, Any], engines: list[dict[str, Any]]) -> None:
    """Mark commits touching engines that are enabled (or broken) here."""
    enabled = [e for e in engines if e.get("enabled")]
    by_module: dict[str, list[str]] = {}
    for e in enabled:
        if e.get("module"):
            by_module.setdefault(e["module"], []).append(e["name"])
    names = sorted({e["name"] for e in enabled} | set(by_module), key=len, reverse=True)
    name_res = [(n, re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", re.I)) for n in names if len(n) > 2]
    for section in ("image_behind", "upcoming"):
        sec = report.get(section) or {}
        touched: set[str] = set()
        for c in sec.get("commits") or []:
            hits: set[str] = set()
            for f in c.get("files") or []:
                m = re.match(r"searx/engines/([\w]+)\.py$", f)
                if m and m.group(1) in by_module:
                    hits.update(by_module[m.group(1)])
            title = c.get("title", "")
            if "engine" in title.lower() or "[fix]" in title.lower():
                for n, rx in name_res:
                    if rx.search(title):
                        hits.update(by_module.get(n, [n]) if n in by_module else [n])
            c["engines"] = sorted(hits)
            c["relevant"] = bool(hits)
            c["is_fix"] = title.lower().startswith("[fix]")
            touched |= hits
        sec["relevant_engines"] = sorted(touched)
        sec["relevant_count"] = sum(1 for c in sec.get("commits") or [] if c.get("relevant"))
