"""Comment-preserving edits to SearXNG's settings.yml (ruamel round-trip)."""

from __future__ import annotations

import difflib
import io
import secrets
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import SingleQuotedScalarString


class SettingsError(ValueError):
    pass


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load(text: str) -> CommentedMap:
    try:
        data = _yaml().load(text)
    except Exception as e:  # ruamel raises many types
        raise SettingsError(f"YAML parse error: {e}") from e
    if not isinstance(data, CommentedMap):
        raise SettingsError("settings.yml must be a mapping at the top level")
    return data


def dump(data: CommentedMap) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def to_plain(node: Any) -> Any:
    if isinstance(node, dict):
        return {str(k): to_plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [to_plain(v) for v in node]
    return node


def validate(text: str) -> CommentedMap:
    data = load(text)
    if data.get("use_default_settings") not in (True, None) and not isinstance(data.get("use_default_settings"), dict):
        raise SettingsError("use_default_settings must stay true (or a mapping) - the dashboard relies on image defaults")
    server = data.get("server") or {}
    if not server.get("secret_key"):
        raise SettingsError("server.secret_key is required")
    fmts = ((data.get("search") or {}).get("formats")) or []
    if "json" not in fmts:
        raise SettingsError("search.formats must include json - the dashboard and local AI tools use it")
    engines = data.get("engines") or []
    if not isinstance(engines, list):
        raise SettingsError("engines must be a list")
    names: set[str] = set()
    for e in engines:
        if not isinstance(e, dict) or not e.get("name"):
            raise SettingsError("every engines entry needs a name")
        if e["name"] in names:
            raise SettingsError(f"duplicate engine entry: {e['name']}")
        names.add(e["name"])
    return data


def diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True), "settings.yml (current)", "settings.yml (new)", n=2,
    ))


def _section(data: CommentedMap, key: str) -> CommentedMap:
    if not isinstance(data.get(key), CommentedMap):
        data[key] = CommentedMap()
    return data[key]


def _engines(data: CommentedMap) -> CommentedSeq:
    if not isinstance(data.get("engines"), CommentedSeq):
        data["engines"] = CommentedSeq()
    return data["engines"]


def _set_seq(parent: CommentedMap, key: str, items: list[str], quote: bool = True) -> None:
    """Replace a list value, keeping the comment ruamel attached to its last item
    (that is where comments *after* the list - e.g. the next section's header - live)."""
    old = parent.get(key)
    trailing = None
    if isinstance(old, CommentedSeq) and len(old):
        trailing = old.ca.items.get(len(old) - 1)
    new = CommentedSeq([SingleQuotedScalarString(i) if quote else i for i in items])
    if not items:
        parent.pop(key, None)  # note: a comment trailing the removed list goes with it
        return
    if trailing:
        new.ca.items[len(new) - 1] = trailing
    if isinstance(old, CommentedSeq):
        for i, item in enumerate(old):
            if i < len(old) - 1 and str(item) in items and i in old.ca.items:
                j = items.index(str(item))
                if j < len(items) - 1:
                    new.ca.items[j] = old.ca.items[i]
    parent[key] = new


def _find_engine(data: CommentedMap, name: str) -> CommentedMap | None:
    for e in _engines(data):
        if isinstance(e, dict) and e.get("name") == name:
            return e
    return None


ENGINE_FIELDS = {"enabled", "weight", "timeout", "shortcut", "api_key", "private"}


def patch_engine(data: CommentedMap, name: str, patch: dict[str, Any], defaults: dict[str, Any] | None,
                 token: str | None = None) -> None:
    """Apply a UI patch to one engine. `defaults` is the image default entry (None for custom engines)."""
    unknown = set(patch) - ENGINE_FIELDS
    if unknown:
        raise SettingsError(f"unsupported engine fields: {', '.join(sorted(unknown))}")
    entry = _find_engine(data, name)
    if entry is None:
        if defaults is None:
            raise SettingsError(f"unknown engine: {name}")
        entry = CommentedMap(name=name)
        _engines(data).append(entry)

    d = defaults or {}
    if "enabled" in patch:
        entry["disabled"] = not patch["enabled"]
        if patch["enabled"] and (d.get("inactive") or entry.get("inactive")):
            entry["inactive"] = False
        # A bare `{name, disabled: <default>}` entry is a no-op; drop the key
        # (entries with other overrides keep it explicit for readability).
        if defaults is not None and len(entry) == 2 and bool(entry["disabled"]) == bool(d.get("disabled", False)):
            entry.pop("disabled", None)
    for key in ("weight", "timeout"):
        if key in patch:
            val = patch[key]
            if val in (None, ""):
                entry.pop(key, None)
            else:
                try:
                    num = float(val)
                except (TypeError, ValueError) as e:
                    raise SettingsError(f"{key} must be a number") from e
                if num <= 0:
                    raise SettingsError(f"{key} must be positive")
                entry[key] = num
    if "shortcut" in patch:
        sc = (patch["shortcut"] or "").strip()
        if not sc:
            entry.pop("shortcut", None)
        elif not sc.replace("_", "").replace("-", "").isalnum():
            raise SettingsError("shortcut must be letters/numbers")
        else:
            entry["shortcut"] = sc
    if "api_key" in patch:
        key = (patch["api_key"] or "").strip()
        if key:
            entry["api_key"] = key
        else:
            entry.pop("api_key", None)
    if "private" in patch:
        if patch["private"]:
            entry["tokens"] = [token or secrets.token_hex(8)]
        else:
            entry.pop("tokens", None)

    # An entry that only carries its name is a no-op: remove it.
    if defaults is not None and len(entry) == 1:
        _engines(data).remove(entry)


GENERAL_FIELDS: dict[str, tuple[str, str, type]] = {
    "instance_name": ("general", "instance_name", str),
    "autocomplete": ("search", "autocomplete", str),
    "safe_search": ("search", "safe_search", int),
    "default_lang": ("search", "default_lang", str),
    "favicon_resolver": ("search", "favicon_resolver", str),
    "request_timeout": ("outgoing", "request_timeout", float),
    "max_request_timeout": ("outgoing", "max_request_timeout", float),
    "image_proxy": ("server", "image_proxy", bool),
    "infinite_scroll": ("ui", "infinite_scroll", bool),
    "results_on_new_tab": ("ui", "results_on_new_tab", bool),
    "center_alignment": ("ui", "center_alignment", bool),
}
SUSPEND_KEYS = ("SearxEngineAccessDenied", "SearxEngineCaptcha", "SearxEngineTooManyRequests",
                "cf_SearxEngineCaptcha", "cf_SearxEngineAccessDenied", "recaptcha_SearxEngineCaptcha")


def read_general(data: CommentedMap, defaults: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, (section, key, _) in GENERAL_FIELDS.items():
        sec = data.get(section) or {}
        if key in sec:
            out[field] = sec[key]
        else:
            out[field] = (defaults.get(section) or {}).get(key)
    susp_user = ((data.get("search") or {}).get("suspended_times")) or {}
    susp_def = ((defaults.get("search") or {}).get("suspended_times")) or {}
    out["suspended_times"] = {k: int(susp_user.get(k, susp_def.get(k, 0)) or 0) for k in SUSPEND_KEYS}
    return to_plain(out)


def patch_general(data: CommentedMap, patch: dict[str, Any]) -> None:
    for field, value in patch.items():
        if field == "suspended_times":
            st = _section(_section(data, "search"), "suspended_times")
            for k, v in (value or {}).items():
                if k not in SUSPEND_KEYS:
                    raise SettingsError(f"unknown suspension key {k}")
                st[k] = int(v)
            continue
        if field not in GENERAL_FIELDS:
            raise SettingsError(f"unsupported setting: {field}")
        section, key, typ = GENERAL_FIELDS[field]
        try:
            _section(data, section)[key] = typ(value) if typ is not bool else bool(value)
        except (TypeError, ValueError) as e:
            raise SettingsError(f"{field}: invalid value") from e


HOSTNAME_LISTS = ("remove", "low_priority", "high_priority")


def read_hostnames(data: CommentedMap) -> dict[str, Any]:
    h = data.get("hostnames") or {}
    out = {k: [str(x) for x in (h.get(k) or [])] for k in HOSTNAME_LISTS}
    rep = h.get("replace") or {}
    out["replace"] = [{"pattern": str(k), "replacement": str(v)} for k, v in rep.items()] if isinstance(rep, dict) else []
    return out


def patch_hostnames(data: CommentedMap, value: dict[str, Any]) -> None:
    import re

    h = _section(data, "hostnames")
    for k in HOSTNAME_LISTS:
        if k in value:
            items = [str(x).strip() for x in value[k] or [] if str(x).strip()]
            for pat in items:
                try:
                    re.compile(pat)
                except re.error as e:
                    raise SettingsError(f"bad regex {pat!r}: {e}") from e
            _set_seq(h, k, items)
    if "replace" in value:
        rep = CommentedMap()
        for item in value["replace"] or []:
            pat, repl = str(item.get("pattern", "")).strip(), str(item.get("replacement", "")).strip()
            if pat and repl:
                rep[pat] = repl
        if rep:
            h["replace"] = rep
        else:
            h.pop("replace", None)


def add_custom_engine(data: CommentedMap, snippet: str, known_modules: list[str], existing_names: set[str]) -> str:
    try:
        parsed = _yaml().load(snippet)
    except Exception as e:
        raise SettingsError(f"YAML parse error: {e}") from e
    if isinstance(parsed, list):
        if len(parsed) != 1:
            raise SettingsError("add one engine at a time")
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        raise SettingsError("engine definition must be a mapping")
    name = str(parsed.get("name", "")).strip()
    module = str(parsed.get("engine", "")).strip()
    if not name or not module:
        raise SettingsError("engine definition needs both name and engine")
    if module not in known_modules:
        raise SettingsError(f"unknown engine module {module!r}")
    if name in existing_names or _find_engine(data, name) is not None:
        raise SettingsError(f"an engine called {name!r} already exists")
    _engines(data).append(parsed)
    return name


def remove_custom_engine(data: CommentedMap, name: str, default_names: set[str]) -> None:
    if name in default_names:
        raise SettingsError("built-in engines can only be disabled, not removed")
    entry = _find_engine(data, name)
    if entry is None:
        raise SettingsError(f"no custom engine {name!r}")
    _engines(data).remove(entry)


def metrics_password(data: CommentedMap) -> str | None:
    pw = (data.get("general") or {}).get("open_metrics")
    return str(pw) if pw else None


def engine_tokens(data: CommentedMap) -> list[str]:
    toks: list[str] = []
    for e in data.get("engines") or []:
        for t in (e.get("tokens") or []) if isinstance(e, dict) else []:
            if str(t) not in toks:
                toks.append(str(t))
    return toks
