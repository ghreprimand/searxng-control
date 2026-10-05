# Architecture

One Python process (FastAPI + asyncio) serves the API and the built React app, and runs a handful of
background collectors. State lives in SQLite. Nothing talks to the outside world except SearXNG itself,
Docker Hub and the GitHub API (for update tracking) and your ntfy server if configured.

## Data sources

| Source | What we get | Cadence | Code |
|---|---|---|---|
| Docker API `GET /containers/searxng/json` + image inspect | state, start time, restart count, image id, version label | 30 s | `Hub.refresh_status` |
| SearXNG `/healthz`, `/config` | liveness; loaded engines, enabled flags, categories, shortcuts | 30 s | `Hub.refresh_status` |
| SearXNG `/metrics` (OpenMetrics, password = `general.open_metrics`) | per-engine request & result counters, median times, reliability | 60 s | `Hub.scrape_metrics` |
| Docker API `GET /containers/searxng/logs?follow=1` | every engine failure SearXNG logs (`ErrorContext(...)`, `engine timeout`), startup banner | streaming | `Hub._logs_loop`, `logparse.py` |
| Canary probe: `GET /search?format=json&categories=general` | which engines returned results / errored / were silent for a real query | every 30 min | `Hub.run_canary` |
| Docker API archive of `/usr/local/searxng/searx/settings.yml` and `searx/engines/*.py` | the engine catalog: every engine the image ships, defaults, which need API keys | once per image | `catalog.py` |
| Docker Hub tags API, GitHub compare/commit API | newest image tag; commits between running and newest; commits on master | 1 h (and right after the image changes) | `upstream.py` |

### Why metrics *and* logs

`/metrics` counters tell us how many requests each engine got (traffic) but they reset on every restart and
only expose a cumulative "reliability". The log stream tells us *what* went wrong and *when* (CAPTCHA vs 403 vs
429 vs parse error, suspension time, upstream host). Combining the two gives a windowed success rate:
`success = (requests − error events) / requests` per hour.

Counter resets are handled by remembering the container's `StartedAt` with the last snapshot
(`kv.metrics_baseline`); if it changed, the new counters are deltas since restart.

### Searches vs. engine requests

SearXNG doesn't count searches. A general search sends one request to every enabled general engine, so the
busiest engine's request count in an hour is used as the "searches (est.)" figure.

## Engine status

Computed in `analytics.engine_states` for each engine, in order:

1. **disabled** – not enabled in `/config`.
2. **blocked** – last block event (CAPTCHA, 403, 429, bot challenge) is still inside its suspension window
   (`suspended_time=` from the log line, else `search.suspended_times`) and nothing succeeded since.
3. With ≥ 3 requests in the last hour: **healthy** (≥ 80 % success), **degraded** (≥ 40 %), else **failing**.
4. Otherwise the last canary probe decides: results → healthy, error → failing, silent → **idle**.
5. Recent errors without traffic → failing; a success in the last 6 h → healthy; else **unknown**.

"Web engines" are enabled engines in the `general` category minus reference engines (Wikipedia, Wikidata,
currency, dictionaries, translators) — the ones that actually return web results.

## Editing settings.yml

`settings_editor.py` uses ruamel.yaml in round-trip mode so comments, quoting and ordering survive. The UI
never writes YAML directly; it sends a structured patch (`engines`, `general`, `hostnames`, `add_engine`,
`remove_engine`) or, in the raw editor, full text.

`applier.Applier.apply`:

1. `validate()` – YAML parses, top level is a mapping, `use_default_settings` kept, `server.secret_key`
   present, `json` still in `search.formats`, engine names unique.
2. Back up the current file to `/data/backups/settings-<ts>.yml` (+ `.json` with the change note; newest 60 kept).
3. Atomic write (temp file + rename, original owner/mode preserved).
4. `docker restart searxng`.
5. Verify for up to 45 s: `/healthz`, `/config`, and a real `!wikipedia` search returning JSON.
6. On failure: capture the last 40 log lines, restore the previous file, restart again, report
   "rolled back" (with the log tail) to the UI.

A single asyncio lock serialises applies/restores/restarts.

Engine patches understand SearXNG's two switches: `disabled` (off by default, still usable via bang) and
`inactive` (not loaded at all). Enabling an engine that ships `inactive: true` sets both to false. Entries
reduced to just `name` are removed so the file stays readable.

**Private engines** use SearXNG's `tokens:` feature: the engine only runs when the request carries a matching
token (saved in each browser's SearXNG preferences). Local AI tools and the dashboard's canary probes don't
send it, which keeps paid API engines from being drained by automation. Manual tests of a private engine do
send it.

## Upstream tracking

SearXNG images are tagged `YYYY.M.D-<commit>`. The running version comes from the image label
`org.opencontainers.image.version`; the newest from Docker Hub. If they differ, GitHub's compare API lists the
commits between them; up to 40 commits get their changed-file list fetched (cached forever by SHA).

A commit is **relevant** if it changes `searx/engines/<module>.py` for an engine you have enabled, or its title
names one of those engines. `fix_available` fires when a relevant commit touches an engine that is currently
blocked/failing/degraded — the "update now, there's a fix for the thing that's broken" signal.

## Updating SearXNG

`UPDATE_METHOD` selects how an update is performed:

- **docker** (default) — `updater.DockerUpdater`, Watchtower-style: inspect the container, pull the image
  reference it was created from, and if the image changed: tag the old image `<repo>:rollback`, stop and rename
  the old container, create a new one with the same configuration (env/labels/entrypoint that came from the
  *old image* are dropped so the new image's defaults apply; user-set values are kept), reconnect extra networks,
  start it, then verify `/healthz` and a real search for up to 90 s. Success removes the old container; failure
  removes the new one, renames the old one back and starts it.
- **agent** — a JSON job is queued for a host-side script (see *Host agent*); used on Unraid to rebuild through
  Unraid's own template machinery.
- **none** — updates are only reported.

`Hub.maybe_auto_update()` runs with the alert loop (every minute) against the cached upstream report. It starts
an update when: an update is available, none is in progress, (agent mode) the agent's heartbeat is fresh, this
image tag wasn't attempted in the last 12 h, and either (a) the newer image touches an engine that is
blocked/failing/degraded here, or (b) mode is *always*, the image is ≥ 1 h old and the last auto-update was
≥ `auto_update_min_hours` ago. When `refresh_status` sees the container's image change it records a lifecycle
entry, sends the "SearXNG updated" notification and re-checks upstream immediately.

## Alerts

`alerts.evaluate()` is a pure function of a snapshot (container, health, engine states, upstream report,
update log, agent heartbeat) → list of conditions. `AlertManager.sync()` runs every minute, opens new alerts,
updates changed ones, resolves cleared ones, and notifies on open/resolve according to the notification
settings (minimum severity, resolve notices).

| Key | Severity | Condition |
|---|---|---|
| `container_down` | critical | Docker reports the container not running |
| `searxng_unhealthy` | critical | `/healthz` failed twice in a row |
| `web_engines_low` | warning | fewer than *N* (default 3) web engines healthy/degraded |
| `engine_down:<name>` | warning | a web engine blocked/failing continuously for *H* hours (default 2) |
| `fix_available` | warning | newer image touches an engine failing here |
| `update_stale` | warning | newer image published > 36 h ago and still not running |
| `update_failed` | warning | last auto-update log line mentions unhealthy/rollback |
| `agent_stale` | info | host agent heartbeat older than 15 min |

## Host agent (optional)

With `UPDATE_METHOD=agent` the container doesn't touch other containers itself. It writes JSON jobs to
`/data/queue/pending/`; a script on the host (`deploy/unraid/host-agent.sh`, run every minute) executes them,
writes results to `queue/done/` and touches `queue/agent-heartbeat`. Jobs: `update` (runs an update script such
as `deploy/unraid/searxng-update.sh`, which uses Unraid's `rebuild_container`) and `notify` (Unraid's notification
system). See [UNRAID.md](UNRAID.md).

## Storage (SQLite, WAL)

| Table | Contents | Retention |
|---|---|---|
| `events` | engine failures and system errors (engine, kind, detail, host, suspension) | 30 d |
| `traffic` | per-scrape request/result deltas and median times per engine | 30 d |
| `probes`, `probe_results` | canary and manual probes, per-engine outcome | 30 d |
| `alerts` | open and resolved alerts | resolved: 30 d |
| `lifecycle` | starts (with version), applies, rollbacks, restarts, update requests | 90 d |
| `kv` | cursors, metrics baseline, upstream report, notification settings, commit-file cache | — |

## Frontend

React 19 + TypeScript + Vite, no component library. Hash routing (`#/engines`, `#/configure/api`), polling via
`usePoll` (pauses when the tab is hidden) and one `EventSource` on `/api/stream` for live events, probes and
log lines. Charts (sparklines, stacked activity bars, heatmap, ring) are small hand-written SVG components in
`components/charts.tsx`. All settings edits go through `ApplyFlow`, which shows the diff, takes a change note
and reports the verified result or the rollback with log tail.
