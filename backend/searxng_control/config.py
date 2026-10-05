"""Runtime configuration, all from environment variables (see docs/CONFIGURATION.md)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _opt_path(name: str) -> Path | None:
    value = os.environ.get(name, "")
    return Path(value) if value else None


@dataclass(frozen=True)
class Config:
    # Where this service reaches SearXNG (inside Docker usually http://searxng:8080).
    searxng_url: str = field(default_factory=lambda: _env("SEARXNG_URL", "http://searxng:8080").rstrip("/"))
    # The URL people use in browsers; only used for links in the UI. Defaults to SEARXNG_URL.
    public_url: str = field(default_factory=lambda: _env("SEARXNG_PUBLIC_URL", "").rstrip("/"))
    # Short label shown under the logo, e.g. "homelab".
    instance_label: str = field(default_factory=lambda: _env("INSTANCE_LABEL", ""))
    container: str = field(default_factory=lambda: _env("SEARXNG_CONTAINER", "searxng"))
    image_repo: str = field(default_factory=lambda: _env("SEARXNG_IMAGE_REPO", "searxng/searxng"))
    github_repo: str = field(default_factory=lambda: _env("SEARXNG_GITHUB_REPO", "searxng/searxng"))
    github_token: str = field(default_factory=lambda: _env("GITHUB_TOKEN", ""))
    docker_socket: str = field(default_factory=lambda: _env("DOCKER_SOCKET", "/var/run/docker.sock"))
    # SearXNG's settings.yml, mounted read-write (the same file the searxng container uses).
    settings_file: Path = field(default_factory=lambda: Path(_env("SEARXNG_SETTINGS", "/searxng/settings.yml")))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/data")))
    static_dir: Path = field(default_factory=lambda: Path(_env("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static"))))
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8890")))
    # How "Update SearXNG" works:
    #   docker - pull the image and recreate the container through the Docker API (default)
    #   agent  - drop a job for a host-side script (e.g. Unraid's rebuild_container); see docs/UNRAID.md
    #   none   - only report available updates
    update_method: str = field(default_factory=lambda: _env("UPDATE_METHOD", "docker").lower())
    # Log shown on the Updates page (agent mode: point it at the host script's log).
    update_log: Path | None = field(default_factory=lambda: _opt_path("UPDATE_LOG"))
    # Optional HTTP basic auth for the whole UI/API.
    auth_user: str = field(default_factory=lambda: _env("CONTROL_USER", "admin"))
    auth_password: str = field(default_factory=lambda: _env("CONTROL_PASSWORD", ""))
    # Default for the host-agent notification channel (Unraid notify); agent mode only.
    notify_host_default: bool = field(default_factory=lambda: _env("NOTIFY_HOST", "0") == "1")
    # Collector cadence (seconds).
    metrics_interval: int = field(default_factory=lambda: int(_env("METRICS_INTERVAL", "60")))
    status_interval: int = field(default_factory=lambda: int(_env("STATUS_INTERVAL", "30")))
    upstream_interval: int = field(default_factory=lambda: int(_env("UPSTREAM_INTERVAL", "3600")))
    retention_days: int = field(default_factory=lambda: int(_env("RETENTION_DAYS", "30")))
    # Disable collectors that need Docker (handy for UI development).
    enable_docker: bool = field(default_factory=lambda: _env("ENABLE_DOCKER", "1") == "1")

    @property
    def settings_path(self) -> Path:
        return self.settings_file

    @property
    def link_url(self) -> str:
        return self.public_url or self.searxng_url

    @property
    def update_log_path(self) -> Path:
        return self.update_log or (self.data_dir / "update.log")

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def queue_dir(self) -> Path:
        return self.data_dir / "queue"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dashboard.db"


CONFIG = Config()
