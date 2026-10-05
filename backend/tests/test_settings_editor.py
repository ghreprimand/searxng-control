import pytest

from searxng_control import settings_editor as se

BASE = """# top comment
use_default_settings: true
server:
  secret_key: "abc"
search:
  formats: [html, json]
engines:
  # Google-backed
  - name: google cse
    shortcut: g
    disabled: false
  - name: brave                   # 429s
    disabled: true
"""

DEFAULTS = {
    "brave": {"name": "brave", "disabled": False, "inactive": False},
    "mojeek": {"name": "mojeek", "disabled": True, "inactive": True},
    "braveapi": {"name": "braveapi", "disabled": False, "inactive": True},
}


def roundtrip(fn):
    data = se.load(BASE)
    fn(data)
    out = se.dump(data)
    se.validate(out)
    return out


def test_comments_survive_and_enable_inactive_engine():
    out = roundtrip(lambda d: se.patch_engine(d, "mojeek", {"enabled": True, "weight": 0.5}, DEFAULTS["mojeek"]))
    assert "# top comment" in out and "# Google-backed" in out and "# 429s" in out
    data = se.to_plain(se.load(out))
    moj = next(e for e in data["engines"] if e["name"] == "mojeek")
    assert moj == {"name": "mojeek", "disabled": False, "inactive": False, "weight": 0.5}


def test_reenable_default_engine_removes_noop_entry():
    out = roundtrip(lambda d: se.patch_engine(d, "brave", {"enabled": True}, DEFAULTS["brave"]))
    names = [e["name"] for e in se.to_plain(se.load(out))["engines"]]
    assert "brave" not in names


def test_api_key_and_private():
    out = roundtrip(lambda d: se.patch_engine(d, "braveapi", {"enabled": True, "api_key": "k123", "private": True},
                                              DEFAULTS["braveapi"], token="tok"))
    e = next(e for e in se.to_plain(se.load(out))["engines"] if e["name"] == "braveapi")
    assert e["api_key"] == "k123" and e["tokens"] == ["tok"] and e["inactive"] is False


def test_validation_errors():
    with pytest.raises(se.SettingsError):
        se.validate("use_default_settings: true\nserver: {secret_key: x}\nsearch: {formats: [html]}\n")
    with pytest.raises(se.SettingsError):
        se.validate("engines: [")
    with pytest.raises(se.SettingsError):
        data = se.load(BASE)
        se.patch_engine(data, "google cse", {"weight": -1}, {"name": "google cse"})


def test_general_and_hostnames():
    def edit(d):
        se.patch_general(d, {"autocomplete": "google", "safe_search": 1, "suspended_times": {"SearxEngineCaptcha": 600}})
        se.patch_hostnames(d, {"remove": [r"(.*\.)?pinterest\.com$"], "high_priority": [], "replace": [{"pattern": "x", "replacement": "y"}]})
    out = roundtrip(edit)
    data = se.load(out)
    g = se.read_general(data, {"search": {"suspended_times": {"SearxEngineAccessDenied": 86400}}})
    assert g["autocomplete"] == "google" and g["safe_search"] == 1
    assert g["suspended_times"]["SearxEngineCaptcha"] == 600 and g["suspended_times"]["SearxEngineAccessDenied"] == 86400
    h = se.read_hostnames(data)
    assert h["remove"] == [r"(.*\.)?pinterest\.com$"] and h["high_priority"] == [] and h["replace"][0]["replacement"] == "y"
    with pytest.raises(se.SettingsError):
        se.patch_hostnames(se.load(BASE), {"remove": ["("]})


def test_custom_engine():
    data = se.load(BASE)
    name = se.add_custom_engine(data, "name: my wiki\nengine: mediawiki\nshortcut: mw\nbase_url: https://wiki.example/\n",
                                ["mediawiki"], set())
    assert name == "my wiki"
    with pytest.raises(se.SettingsError):
        se.add_custom_engine(data, "name: my wiki\nengine: mediawiki\n", ["mediawiki"], set())
    with pytest.raises(se.SettingsError):
        se.add_custom_engine(data, "name: x\nengine: nope\n", ["mediawiki"], set())
    se.remove_custom_engine(data, "my wiki", {"brave"})
    se.validate(se.dump(data))


def test_hostnames_keep_quotes_and_trailing_section_comment():
    text = """use_default_settings: true
server:
  secret_key: "abc"
search:
  formats: [html, json]
hostnames:
  high_priority:
    - '(.*\\.)?wikipedia\\.org$'

# --- Engines ---
engines:
  - name: brave
    disabled: true
"""
    data = se.load(text)
    se.patch_hostnames(data, {"high_priority": [r"(.*\.)?wikipedia\.org$", r"(.*\.)?github\.com$"]})
    out = se.dump(data)
    assert "# --- Engines ---" in out
    assert r"- '(.*\.)?github\.com$'" in out
    diff = se.diff(text, out)
    changed = [l for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    assert changed == [r"+    - '(.*\.)?github\.com$'"]
