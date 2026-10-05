"""FastAPI app: API under /api, the built frontend everywhere else."""

from __future__ import annotations

import base64
import logging
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import build_router
from .config import CONFIG, Config
from .hub import Hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


class BasicAuth:
    """Pure-ASGI HTTP basic auth (works with streaming/SSE responses). /healthz stays open."""

    def __init__(self, app, user: str, password: str):
        self.app, self.user, self.password = app, user, password

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            return await self.app(scope, receive, send)
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
        ok = False
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(user, self.user) and secrets.compare_digest(pw, self.password)
            except (ValueError, UnicodeDecodeError):
                ok = False
        if ok:
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"www-authenticate", b'Basic realm="SearXNG Control"'), (b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"Authentication required"})


def create_app(cfg: Config = CONFIG) -> FastAPI:
    hub = Hub(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await hub.refresh_status()
        await hub.start()
        yield
        await hub.stop()

    app = FastAPI(title="SearXNG Control", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.hub = hub
    app.include_router(build_router(hub))

    @app.get("/healthz")
    async def healthz():
        return JSONResponse({"ok": True})

    static = cfg.static_dir
    if (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    if cfg.auth_password:
        app.add_middleware(BasicAuth, user=cfg.auth_user, password=cfg.auth_password)
    return app


app = create_app()


def run() -> None:
    if not CONFIG.auth_password and CONFIG.host not in ("127.0.0.1", "localhost", "::1"):
        logging.getLogger(__name__).warning(
            "No CONTROL_PASSWORD set and listening on %s - anyone who can reach this port can change SearXNG "
            "and restart containers. Keep it on a private network or set CONTROL_PASSWORD.", CONFIG.host)
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, proxy_headers=True, forwarded_allow_ips="*", log_level="warning")


if __name__ == "__main__":
    run()
