"""Minimal async Docker Engine API client over the unix socket.

Only the handful of endpoints the dashboard needs: inspect, restart, logs
(tail + follow), and archive (to read files out of the SearXNG image).
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import httpx


class DockerError(RuntimeError):
    pass


def split_ref(ref: str) -> tuple[str, str]:
    """'docker.io/searxng/searxng:latest' -> ('docker.io/searxng/searxng', 'latest')."""
    ref = ref.split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = ref.rsplit(":", 1)
        return repo, tag
    return ref, "latest"


def _split_ts(line: str) -> tuple[float, str]:
    """Docker prefixes each line with an RFC3339Nano UTC timestamp when timestamps=1."""
    stamp, _, rest = line.partition(" ")
    try:
        # Trim nanoseconds to microseconds for fromisoformat.
        base, _, frac = stamp.rstrip("Z").partition(".")
        dt = datetime.fromisoformat(f"{base}.{(frac + '000000')[:6]}").replace(tzinfo=timezone.utc)
        return dt.timestamp(), rest
    except ValueError:
        return 0.0, line


class LogDemux:
    """Decode Docker's multiplexed stdout/stderr stream (non-TTY containers)."""

    def __init__(self) -> None:
        self._buf = b""
        self._text = ""
        self._mux: bool | None = None

    def feed(self, chunk: bytes) -> list[str]:
        self._buf += chunk
        if self._mux is None and len(self._buf) >= 8:
            self._mux = self._buf[0] in (0, 1, 2) and self._buf[1:4] == b"\x00\x00\x00"
        if self._mux is None:
            return []
        if self._mux:
            while len(self._buf) >= 8:
                size = int.from_bytes(self._buf[4:8], "big")
                if len(self._buf) < 8 + size:
                    break
                self._text += self._buf[8 : 8 + size].decode("utf-8", "replace")
                self._buf = self._buf[8 + size :]
        else:
            self._text += self._buf.decode("utf-8", "replace")
            self._buf = b""
        *lines, self._text = self._text.split("\n")
        return lines

    def flush(self) -> list[str]:
        rest, self._text = self._text, ""
        return [rest] if rest else []


class Docker:
    def __init__(self, socket_path: str):
        self._transport = httpx.AsyncHTTPTransport(uds=socket_path)
        self._client = httpx.AsyncClient(transport=self._transport, base_url="http://docker/v1.43", timeout=30)

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, method: str, path: str, **kw: Any) -> Any:
        r = await self._client.request(method, path, **kw)
        if r.status_code >= 400:
            raise DockerError(f"{method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    async def ping(self) -> bool:
        try:
            r = await self._client.get("/_ping", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def inspect(self, name: str) -> dict:
        return await self._json("GET", f"/containers/{name}/json")

    async def image(self, ref: str) -> dict:
        return await self._json("GET", f"/images/{ref}/json")

    async def restart(self, name: str, timeout: int = 10) -> None:
        r = await self._client.post(f"/containers/{name}/restart", params={"t": timeout}, timeout=timeout + 30)
        if r.status_code >= 400:
            raise DockerError(f"restart {name}: {r.status_code} {r.text[:200]}")

    async def logs_tail(self, name: str, lines: int = 200) -> list[tuple[float, str]]:
        r = await self._client.get(
            f"/containers/{name}/logs",
            params={"stdout": 1, "stderr": 1, "timestamps": 1, "tail": lines},
        )
        if r.status_code >= 400:
            raise DockerError(f"logs {name}: {r.status_code}")
        demux = LogDemux()
        out = demux.feed(r.content) + demux.flush()
        return [_split_ts(line) for line in out if line]

    async def follow_logs(self, name: str, since: float) -> AsyncIterator[tuple[float, str]]:
        """Yield (timestamp, line) forever until the container stops or the stream drops."""
        params = {"stdout": 1, "stderr": 1, "timestamps": 1, "follow": 1, "since": int(since)}
        async with self._client.stream(
            "GET", f"/containers/{name}/logs", params=params, timeout=httpx.Timeout(10, read=None)
        ) as r:
            if r.status_code >= 400:
                raise DockerError(f"follow logs {name}: {r.status_code}")
            demux = LogDemux()
            async for chunk in r.aiter_raw():
                for line in demux.feed(chunk):
                    if line:
                        yield _split_ts(line)

    # -- lifecycle operations used by the built-in updater -----------------------
    async def pull(self, ref: str) -> None:
        """docker pull <ref>; raises DockerError on failure."""
        repo, tag = split_ref(ref)
        async with self._client.stream("POST", "/images/create", params={"fromImage": repo, "tag": tag},
                                       timeout=httpx.Timeout(30, read=600)) as r:
            if r.status_code >= 400:
                raise DockerError(f"pull {ref}: {r.status_code} {(await r.aread())[:200]!r}")
            async for line in r.aiter_lines():
                if '"error"' in line:
                    raise DockerError(f"pull {ref}: {line[:300]}")

    async def tag(self, image: str, repo: str, tag: str) -> None:
        r = await self._client.post(f"/images/{image}/tag", params={"repo": repo, "tag": tag})
        if r.status_code >= 400:
            raise DockerError(f"tag {image}: {r.status_code} {r.text[:200]}")

    async def stop(self, name: str, timeout: int = 15) -> None:
        r = await self._client.post(f"/containers/{name}/stop", params={"t": timeout}, timeout=timeout + 30)
        if r.status_code not in (204, 304):
            raise DockerError(f"stop {name}: {r.status_code} {r.text[:200]}")

    async def start(self, name: str) -> None:
        r = await self._client.post(f"/containers/{name}/start", timeout=60)
        if r.status_code not in (204, 304):
            raise DockerError(f"start {name}: {r.status_code} {r.text[:200]}")

    async def rename(self, name: str, new_name: str) -> None:
        r = await self._client.post(f"/containers/{name}/rename", params={"name": new_name})
        if r.status_code >= 400:
            raise DockerError(f"rename {name}: {r.status_code} {r.text[:200]}")

    async def remove(self, name: str, force: bool = False) -> None:
        r = await self._client.delete(f"/containers/{name}", params={"force": int(force)}, timeout=60)
        if r.status_code not in (204, 404):
            raise DockerError(f"remove {name}: {r.status_code} {r.text[:200]}")

    async def create(self, name: str, body: dict) -> str:
        r = await self._client.post("/containers/create", params={"name": name}, json=body, timeout=60)
        if r.status_code >= 400:
            raise DockerError(f"create {name}: {r.status_code} {r.text[:300]}")
        return r.json()["Id"]

    async def connect(self, network: str, container: str, endpoint: dict) -> None:
        r = await self._client.post(f"/networks/{network}/connect",
                                    json={"Container": container, "EndpointConfig": endpoint})
        if r.status_code >= 400:
            raise DockerError(f"connect {network}: {r.status_code} {r.text[:200]}")

    async def read_file(self, name: str, path: str) -> bytes:
        """Read a single file from a container via the archive endpoint."""
        r = await self._client.get(f"/containers/{name}/archive", params={"path": path}, timeout=60)
        if r.status_code >= 400:
            raise DockerError(f"archive {path}: {r.status_code}")
        with tarfile.open(fileobj=io.BytesIO(r.content)) as tar:
            member = next(m for m in tar.getmembers() if m.isfile())
            fh = tar.extractfile(member)
            return fh.read() if fh else b""

    async def read_tree(self, name: str, path: str, suffix: str = "") -> dict[str, bytes]:
        """Read every file under a directory (used for searx/engines/*.py)."""
        r = await self._client.get(f"/containers/{name}/archive", params={"path": path}, timeout=120)
        if r.status_code >= 400:
            raise DockerError(f"archive {path}: {r.status_code}")
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(r.content)) as tar:
            for m in tar.getmembers():
                if m.isfile() and m.name.endswith(suffix) and "__pycache__" not in m.name:
                    fh = tar.extractfile(m)
                    if fh:
                        files[m.name.rsplit("/", 1)[-1]] = fh.read()
        return files
