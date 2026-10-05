# HTTP API

Base: `http://<host>:8890/api`. JSON in and out. Interactive docs (OpenAPI) at `/api/docs`.
Errors return `{"detail": "..."}` with 4xx/5xx. Settings-changing calls return an **ApplyResult**:

```json
{"ok": true, "message": "Applied and SearXNG is healthy", "rolled_back": false,
 "backup": "settings-20261005-130720.yml", "log_tail": [], "duration_s": 4.3}
```

## Monitoring

| Method & path | Description |
|---|---|
| `GET /overview` | container/version/health, summary counters, enabled engines with status + 24 h sparkline, 24 h hourly series, last probe, active alerts, update summary, recent events |
| `GET /engines` | full catalog merged with overrides and runtime state, plus status per engine |
| `GET /engines/{name}` | one engine: state, 48 h series, error kinds (7 d), events, probe history, settings override and image default |
| `POST /engines/{name}/test` | `{"query": "..."}` → runs a search with only this engine (via its bang; sends the private token if needed) |
| `GET /events?engine=&kind=&limit=&before=` | event history; `kind=blocks` for CAPTCHA/403/429/challenge only |
| `GET /activity?range=48h\|7d\|30d` | heatmap, series, kinds, per-engine counts, lifecycle |
| `GET /logs?lines=300` | tail of the SearXNG container log |
| `GET /stream` | Server-Sent Events: `event`, `log`, `probe`, `traffic`, `lifecycle`, `upstream` |
| `GET /probes?limit=` | probe history with per-engine results |
| `POST /probes/run` | `{"query": null\|"..."}` → run a canary probe now |

## Configuration

| Method & path | Description |
|---|---|
| `GET /config` | general settings, site rules, file info, available modules, custom engines, private token, option lists |
| `POST /config/preview` | ConfigPatch → `{"diff", "note"}` without writing |
| `POST /config/apply` | ConfigPatch → ApplyResult |
| `GET /config/raw` | `{"text", "file"}` |
| `POST /config/raw/preview` | `{"text"}` → `{"diff"}` (validates) |
| `PUT /config/raw` | `{"text", "note"}` → ApplyResult |
| `GET /backups` | list |
| `GET /backups/{name}` | text + diff vs. current |
| `POST /backups/{name}/restore` | ApplyResult |
| `POST /searxng/restart` | restart + verify |

**ConfigPatch**

```json
{
  "engines": {
    "braveapi": {"enabled": true, "api_key": "…", "private": true},
    "mojeek":   {"weight": 0.5, "timeout": 4},
    "qwant":    {"enabled": false}
  },
  "general":   {"autocomplete": "google", "safe_search": 0, "suspended_times": {"SearxEngineCaptcha": 1800}},
  "hostnames": {"remove": ["(.*\\.)?pinterest\\.com$"], "low_priority": [], "high_priority": [],
                "replace": [{"pattern": "(.*\\.)?reddit\\.com$", "replacement": "old.reddit.com"}]},
  "add_engine": "name: my wiki\nengine: mediawiki\nbase_url: https://wiki.example/\n",
  "remove_engine": "my wiki",
  "note": "why"
}
```

Engine fields: `enabled`, `weight` (null = default), `timeout` (null = default), `shortcut`, `api_key`
(empty string removes it), `private` (token-gate the engine). General fields: `instance_name`, `autocomplete`,
`safe_search`, `default_lang`, `favicon_resolver`, `request_timeout`, `max_request_timeout`, `image_proxy`,
`infinite_scroll`, `results_on_new_tab`, `center_alignment`, `suspended_times`.

## Updates & alerts

| Method & path | Description |
|---|---|
| `GET /updates` | running version, upstream report (latest tag, commits behind with relevance, upcoming on master), update log, update method, running/recent updates, auto-update settings |
| `POST /updates/check` | refresh the upstream report now |
| `POST /updates/apply` | start an update now (docker method: pull + recreate; agent method: queue a job) |
| `GET /alerts` | active + history + notification settings |
| `PUT /alerts/settings` | `unraid` (host-agent notifications), `ntfy_url`, `ntfy_token`, `min_severity`, `notify_resolved`, `min_web_engines`, `engine_blocked_hours`, `update_stale_hours`, `probe_interval_min`, `auto_update` (`always`/`fixes`/`off`), `auto_update_min_hours`, `notify_updates` |
| `POST /alerts/test` | send a test notification on all enabled channels |
| `GET /meta` | viewer identity (from `Tailscale-User-Login`/`Remote-User` headers), public URL, label, update method |
