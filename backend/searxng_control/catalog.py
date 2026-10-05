"""Engine catalog: what SearXNG *can* run (image defaults), what you changed
(settings.yml overrides) and what is actually loaded (/config)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .docker_api import Docker

SEARX_ROOT = "/usr/local/searxng/searx"

_ABOUT_BOOL = {
    key: re.compile(r"""["']%s["']\s*:\s*(True|False)""" % key)
    for key in ("require_api_key", "use_official_api")
}
_ABOUT_STR = {
    key: re.compile(r"""["']%s["']\s*:\s*["']([^"']+)["']""" % key)
    for key in ("website", "results")
}
_CATEGORIES = re.compile(r"^categories\s*(?::[^=]*)?=\s*\[([^\]]*)\]", re.M)


def parse_module(src: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for key, rx in _ABOUT_BOOL.items():
        m = rx.search(src)
        if m:
            info[key] = m.group(1) == "True"
    for key, rx in _ABOUT_STR.items():
        m = rx.search(src)
        if m:
            info[key] = m.group(1)
    m = _CATEGORIES.search(src)
    if m:
        info["categories"] = [c.strip().strip("\"'") for c in m.group(1).split(",") if c.strip()]
    info["api_key_attr"] = bool(re.search(r"^api_key\s*(?::[^=]*)?=", src, re.M))
    return info


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [c.strip() for c in v.split(",") if c.strip()]
    return [str(c) for c in v]


def build_defaults(settings_text: str, modules: dict[str, bytes]) -> dict[str, Any]:
    data = YAML(typ="safe").load(settings_text) or {}
    about = {name[:-3]: parse_module(src.decode("utf-8", "replace")) for name, src in modules.items()}
    engines = []
    for e in data.get("engines") or []:
        if not isinstance(e, dict) or "name" not in e:
            continue
        mod = e.get("engine", "")
        info = about.get(mod, {})
        engines.append({
            "name": e["name"],
            "module": mod,
            "shortcut": e.get("shortcut"),
            "categories": _as_list(e.get("categories")) or info.get("categories", []),
            "disabled": bool(e.get("disabled", False)),
            "inactive": bool(e.get("inactive", False)),
            "timeout": e.get("timeout"),
            "weight": e.get("weight"),
            "requires_api_key": bool(info.get("require_api_key")) or ("api_key" in e),
            "official_api": bool(info.get("use_official_api")),
            "website": (e.get("about") or {}).get("website") or info.get("website"),
            "results_format": info.get("results"),
        })
    return {
        "engines": engines,
        "modules": sorted(about),
        "search": data.get("search") or {},
        "outgoing": data.get("outgoing") or {},
        "ui": data.get("ui") or {},
    }


async def load_defaults(docker: Docker, container: str, image_id: str, cache_dir: Path) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"catalog-{image_id.replace('sha256:', '')[:16]}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    settings_text = (await docker.read_file(container, f"{SEARX_ROOT}/settings.yml")).decode("utf-8")
    modules = await docker.read_tree(container, f"{SEARX_ROOT}/engines", ".py")
    defaults = build_defaults(settings_text, modules)
    for old in cache_dir.glob("catalog-*.json"):
        old.unlink(missing_ok=True)
    cache.write_text(json.dumps(defaults))
    return defaults


def merge(defaults: dict[str, Any], user_settings: dict[str, Any], runtime: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One row per engine with default, override and runtime state combined."""
    overrides = {e["name"]: e for e in (user_settings.get("engines") or []) if isinstance(e, dict) and "name" in e}
    loaded = {e["name"]: e for e in ((runtime or {}).get("engines") or [])}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def row(base: dict[str, Any], custom: bool) -> dict[str, Any]:
        name = base["name"]
        ov = overrides.get(name, {})
        rt = loaded.get(name)
        eff_disabled = bool(ov.get("disabled", base.get("disabled", False)))
        eff_inactive = bool(ov.get("inactive", base.get("inactive", False)))
        api_key = ov.get("api_key", "")
        return {
            "name": name,
            "module": ov.get("engine", base.get("module")),
            "shortcut": (rt or {}).get("shortcut") or ov.get("shortcut") or base.get("shortcut"),
            "categories": (rt or {}).get("categories") or _as_list(ov.get("categories")) or base.get("categories", []),
            "enabled": bool(rt["enabled"]) if rt else False,
            "loaded": rt is not None,
            "disabled": eff_disabled,
            "inactive": eff_inactive,
            "default_disabled": bool(base.get("disabled", False)),
            "default_inactive": bool(base.get("inactive", False)),
            "timeout": ov.get("timeout", base.get("timeout")),
            "weight": ov.get("weight", base.get("weight")),
            "requires_api_key": bool(base.get("requires_api_key")),
            "has_api_key": bool(api_key) and str(api_key) not in ("", "YOUR-API-KEY"),
            "private": bool(ov.get("tokens")),
            "official_api": bool(base.get("official_api")),
            "website": base.get("website"),
            "overridden": sorted(k for k in ov if k != "name"),
            "custom": custom,
        }

    for base in defaults.get("engines", []):
        rows.append(row(base, custom=False))
        seen.add(base["name"])
    for name, ov in overrides.items():
        if name not in seen and "engine" in ov:
            rows.append(row({"name": name, "module": ov.get("engine"), "categories": _as_list(ov.get("categories"))}, custom=True))
    return rows
