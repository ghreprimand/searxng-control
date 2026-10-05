"""File queue to a host agent (UPDATE_METHOD=agent).

Some hosts want updates done by their own tooling - e.g. Unraid's
rebuild_container so the container keeps matching its template - and have a
host-side notify command. The container drops JSON jobs into queue/pending/ and
a script on the host (deploy/unraid/host-agent.sh) runs them and writes results
to queue/done/.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class HostQueue:
    def __init__(self, root: Path):
        self.root = root
        self.pending = root / "pending"
        self.done = root / "done"
        for d in (self.pending, self.done):
            d.mkdir(parents=True, exist_ok=True)

    def submit(self, action: str, **payload: Any) -> str:
        job_id = f"{int(time.time())}-{action}-{uuid.uuid4().hex[:6]}"
        body = {"id": job_id, "action": action, "submitted": time.time(), **payload}
        tmp = self.pending / f".{job_id}.tmp"
        tmp.write_text(json.dumps(body))
        tmp.rename(self.pending / f"{job_id}.json")
        return job_id

    def pending_jobs(self, action: str | None = None) -> list[dict]:
        jobs = []
        for p in sorted(self.pending.glob("*.json")):
            try:
                job = json.loads(p.read_text())
            except ValueError:
                continue
            if action is None or job.get("action") == action:
                jobs.append(job)
        return jobs

    def results(self, action: str | None = None, limit: int = 20) -> list[dict]:
        out = []
        for p in sorted(self.done.glob("*.json"), reverse=True):
            try:
                res = json.loads(p.read_text())
            except ValueError:
                continue
            req = res.get("request") or {}
            if action is None or req.get("action") == action:
                out.append(res)
            if len(out) >= limit:
                break
        return out

    def agent_heartbeat(self) -> float | None:
        hb = self.root / "agent-heartbeat"
        try:
            return float(hb.read_text().strip())
        except (OSError, ValueError):
            return None
