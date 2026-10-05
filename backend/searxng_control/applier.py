"""Write settings.yml safely: backup -> write -> restart -> verify -> roll back on failure."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .db import DB
from .docker_api import Docker
from .searxng_client import SearXNG
from . import settings_editor as se

MAX_BACKUPS = 60


@dataclass
class ApplyResult:
    ok: bool
    message: str
    rolled_back: bool = False
    backup: str | None = None
    log_tail: list[str] = field(default_factory=list)
    duration_s: float = 0.0


class Applier:
    def __init__(self, cfg: Config, db: DB, docker: Docker | None, sx: SearXNG):
        self.cfg, self.db, self.docker, self.sx = cfg, db, docker, sx
        self.lock = asyncio.Lock()
        self.cfg.backups_dir.mkdir(parents=True, exist_ok=True)

    # -- file helpers ----------------------------------------------------
    def read(self) -> str:
        return self.cfg.settings_path.read_text()

    def _write(self, text: str) -> None:
        path = self.cfg.settings_path
        st = path.stat()
        tmp = path.with_suffix(".yml.dashboard-tmp")
        tmp.write_text(text)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.chmod(tmp, st.st_mode & 0o777)
        os.replace(tmp, path)

    def backup(self, reason: str) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"settings-{stamp}.yml"
        dest = self.cfg.backups_dir / name
        n = 1
        while dest.exists():
            name = f"settings-{stamp}-{n}.yml"
            dest = self.cfg.backups_dir / name
            n += 1
        dest.write_text(self.read())
        dest.with_suffix(".json").write_text(json.dumps({"reason": reason, "ts": time.time()}))
        backups = sorted(self.cfg.backups_dir.glob("settings-*.yml"))
        for old in backups[:-MAX_BACKUPS]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
        return name

    def list_backups(self) -> list[dict]:
        out = []
        for p in sorted(self.cfg.backups_dir.glob("settings-*.yml"), reverse=True):
            meta: dict = {}
            mp = p.with_suffix(".json")
            if mp.exists():
                try:
                    meta = json.loads(mp.read_text())
                except ValueError:
                    meta = {}
            out.append({"name": p.name, "ts": meta.get("ts", p.stat().st_mtime), "reason": meta.get("reason", ""),
                        "size": p.stat().st_size})
        return out

    def read_backup(self, name: str) -> str:
        p = (self.cfg.backups_dir / name).resolve()
        if p.parent != self.cfg.backups_dir.resolve() or not p.name.startswith("settings-") or not p.exists():
            raise FileNotFoundError(name)
        return p.read_text()

    # -- restart & verify -----------------------------------------------
    async def _verify(self, timeout: float = 45) -> bool:
        deadline = time.monotonic() + timeout
        await asyncio.sleep(3)
        while time.monotonic() < deadline:
            if await self.sx.healthy():
                try:
                    await self.sx.config()
                    out = await self.sx.search("wikipedia", engines="wikipedia", timeout=15)
                    if out.ok:
                        return True
                except Exception:
                    pass
            await asyncio.sleep(2)
        return False

    async def _restart(self) -> None:
        if not self.docker:
            raise RuntimeError("Docker access is disabled; cannot restart SearXNG")
        await self.docker.restart(self.cfg.container)

    async def _log_tail(self) -> list[str]:
        if not self.docker:
            return []
        try:
            return [line for _, line in await self.docker.logs_tail(self.cfg.container, 40)]
        except Exception:
            return []

    async def restart_only(self) -> ApplyResult:
        async with self.lock:
            t0 = time.monotonic()
            await self._restart()
            ok = await self._verify()
            self.db.lifecycle("restart", "manual restart" + ("" if ok else " (unhealthy)"))
            return ApplyResult(ok, "SearXNG restarted" if ok else "SearXNG did not come back healthy",
                               log_tail=[] if ok else await self._log_tail(), duration_s=time.monotonic() - t0)

    async def apply(self, new_text: str, reason: str) -> ApplyResult:
        se.validate(new_text)
        async with self.lock:
            t0 = time.monotonic()
            current = self.read()
            if current == new_text:
                return ApplyResult(True, "No changes", duration_s=0)
            backup = self.backup(reason)
            self._write(new_text)
            try:
                await self._restart()
            except Exception as e:
                self._write(current)
                return ApplyResult(False, f"Restart failed: {e}", rolled_back=True, backup=backup)
            if await self._verify():
                self.db.lifecycle("apply", reason)
                return ApplyResult(True, "Applied and SearXNG is healthy", backup=backup,
                                   duration_s=time.monotonic() - t0)
            tail = await self._log_tail()
            self._write(current)
            await self._restart()
            healthy_again = await self._verify()
            self.db.lifecycle("rollback", f"{reason} (restored {backup})")
            msg = "SearXNG failed to start with the new settings; previous settings restored"
            if not healthy_again:
                msg += " - but SearXNG is STILL unhealthy, check the container"
            return ApplyResult(False, msg, rolled_back=True, backup=backup, log_tail=tail,
                               duration_s=time.monotonic() - t0)

    async def restore(self, name: str) -> ApplyResult:
        text = self.read_backup(name)
        return await self.apply(text, f"restore {name}")


def settings_file_info(path: Path) -> dict:
    st = path.stat()
    return {"path": str(path), "mtime": st.st_mtime, "size": st.st_size}
