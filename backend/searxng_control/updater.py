"""Built-in SearXNG updater (UPDATE_METHOD=docker).

Pulls the image the container was created from and, if it changed, recreates the
container with the same configuration - the way Watchtower does it - then
verifies SearXNG and rolls back to the previous container if it isn't healthy.

Configuration that was baked into the *old image* (env defaults, entrypoint,
labels, healthcheck) is not copied, so the new image's defaults apply; only what
the user set on the container is carried over.
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .docker_api import Docker, DockerError, split_ref
from .searxng_client import SearXNG


@dataclass
class UpdateResult:
    ok: bool
    message: str
    from_version: str | None = None
    to_version: str | None = None
    rolled_back: bool = False
    log: list[str] = field(default_factory=list)


def _env_dict(env: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in env or []:
        k, _, v = item.partition("=")
        out[k] = v
    return out


def build_create_body(container: dict[str, Any], old_image: dict[str, Any], new_image: dict[str, Any], ref: str) -> dict[str, Any]:
    """Reconstruct a /containers/create body from an inspected container, swapping the image."""
    cfg = copy.deepcopy(container.get("Config") or {})
    old_cfg = old_image.get("Config") or {}
    new_cfg = new_image.get("Config") or {}
    cfg["Image"] = ref

    # Env: keep only what differs from the old image's defaults, layered over the new image's.
    old_env, cur_env = _env_dict(old_cfg.get("Env")), _env_dict(cfg.get("Env"))
    user_env = {k: v for k, v in cur_env.items() if old_env.get(k) != v}
    merged = {**_env_dict(new_cfg.get("Env")), **user_env}
    cfg["Env"] = [f"{k}={v}" for k, v in merged.items()]

    # Fields inherited from the image: drop them so the new image's values apply.
    for key in ("Cmd", "Entrypoint", "WorkingDir", "User", "Healthcheck", "StopSignal"):
        if key in cfg and cfg.get(key) == old_cfg.get(key):
            cfg.pop(key, None)
    old_labels = old_cfg.get("Labels") or {}
    cfg["Labels"] = {k: v for k, v in (cfg.get("Labels") or {}).items() if old_labels.get(k) != v}
    if cfg.get("Volumes") == old_cfg.get("Volumes"):
        cfg.pop("Volumes", None)
    if cfg.get("ExposedPorts") == old_cfg.get("ExposedPorts"):
        cfg.pop("ExposedPorts", None)
    if cfg.get("Hostname") and container.get("Id", "").startswith(cfg["Hostname"]):
        cfg.pop("Hostname", None)  # auto-generated from the old container id

    body: dict[str, Any] = {**cfg, "HostConfig": copy.deepcopy(container.get("HostConfig") or {})}
    networks = ((container.get("NetworkSettings") or {}).get("Networks")) or {}
    mode = body["HostConfig"].get("NetworkMode", "")
    first = mode if mode in networks else (next(iter(networks)) if networks else None)
    if first and first not in ("host", "none") and not str(mode).startswith("container:"):
        body["NetworkingConfig"] = {"EndpointsConfig": {first: endpoint_config(networks[first], container)}}
    return body


def endpoint_config(net: dict[str, Any], container: dict[str, Any]) -> dict[str, Any]:
    short_id = container.get("Id", "")[:12]
    out: dict[str, Any] = {}
    aliases = [a for a in (net.get("Aliases") or []) if a != short_id]
    if aliases:
        out["Aliases"] = aliases
    for key in ("IPAMConfig", "Links", "DriverOpts", "MacAddress"):
        if net.get(key):
            out[key] = net[key]
    return out


class DockerUpdater:
    def __init__(self, docker: Docker, sx: SearXNG, container: str, log_path: Path):
        self.docker, self.sx, self.container, self.log_path = docker, sx, container, log_path
        self.lock = asyncio.Lock()
        self.running = False

    def _log(self, lines: list[str], msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        lines.append(line)
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    async def _healthy(self, timeout: float = 90) -> bool:
        deadline = time.monotonic() + timeout
        await asyncio.sleep(3)
        while time.monotonic() < deadline:
            if await self.sx.healthy():
                out = await self.sx.search("wikipedia", engines="wikipedia", timeout=15)
                if out.ok:
                    return True
            await asyncio.sleep(2)
        return False

    async def update(self) -> UpdateResult:
        async with self.lock:
            self.running = True
            try:
                return await self._update()
            finally:
                self.running = False

    async def _update(self) -> UpdateResult:
        lines: list[str] = []
        d = self.docker
        info = await d.inspect(self.container)
        ref = (info.get("Config") or {}).get("Image") or ""
        if not ref or ref.startswith("sha256:") or "@" in ref:
            return UpdateResult(False, f"container image {ref!r} is pinned; nothing to pull")
        old_image = await d.image(info["Image"])
        old_version = ((old_image.get("Config") or {}).get("Labels") or {}).get("org.opencontainers.image.version")
        try:
            await d.pull(ref)
        except DockerError as e:
            self._log(lines, f"pull failed ({e}) - keeping current image")
            return UpdateResult(False, f"pull failed: {e}", old_version, log=lines)
        new_image = await d.image(ref)
        new_version = ((new_image.get("Config") or {}).get("Labels") or {}).get("org.opencontainers.image.version")
        if new_image["Id"] == info["Image"]:
            self._log(lines, f"up to date ({old_version})")
            return UpdateResult(True, f"Already up to date ({old_version})", old_version, old_version, log=lines)

        repo, _ = split_ref(ref)
        self._log(lines, f"updating to {new_version}")
        await d.tag(info["Image"], repo, "rollback")
        body = build_create_body(info, old_image, new_image, ref)
        extra_networks = {k: v for k, v in ((info.get("NetworkSettings") or {}).get("Networks") or {}).items()
                          if k not in ((body.get("NetworkingConfig") or {}).get("EndpointsConfig") or {})
                          and k not in ("host", "none") and body["HostConfig"].get("NetworkMode") not in ("host",)}
        old_name = f"{self.container}-previous-{int(time.time())}"
        was_running = (info.get("State") or {}).get("Running")

        await d.stop(self.container)
        await d.rename(self.container, old_name)
        new_id = None
        try:
            new_id = await d.create(self.container, body)
            for net, ep in extra_networks.items():
                await d.connect(net, new_id, endpoint_config(ep, info))
            await d.start(new_id)
        except DockerError as e:
            self._log(lines, f"recreate failed ({e}) - restoring previous container")
            await self._restore(new_id, old_name, was_running)
            return UpdateResult(False, f"recreate failed: {e}", old_version, new_version, rolled_back=True, log=lines)

        if await self._healthy():
            await d.remove(old_name)
            self._log(lines, f"update OK ({new_version})")
            return UpdateResult(True, f"Updated {old_version} -> {new_version}", old_version, new_version, log=lines)

        self._log(lines, "new image unhealthy - rolling back")
        await self._restore(new_id, old_name, was_running)
        healthy = await self._healthy(60)
        self._log(lines, "rollback OK" if healthy else "rollback ALSO unhealthy")
        return UpdateResult(False, f"{new_version} failed its health check; rolled back to {old_version}",
                            old_version, new_version, rolled_back=True, log=lines)

    async def _restore(self, new_id: str | None, old_name: str, was_running: bool | None) -> None:
        d = self.docker
        if new_id:
            try:
                await d.remove(new_id, force=True)
            except DockerError:
                pass
        await d.rename(old_name, self.container)
        if was_running:
            await d.start(self.container)
