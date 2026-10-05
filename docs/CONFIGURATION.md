# Configuration

Everything is set with environment variables on the `searxng-control` container. Alert thresholds, probe
interval, notification channels and auto-update policy are set in the UI (Alerts and Updates pages) and stored
in the database.

| Variable | Default | Purpose |
|---|---|---|
| `SEARXNG_URL` | `http://searxng:8080` | Where the panel reaches SearXNG (container-to-container URL). |
| `SEARXNG_PUBLIC_URL` | same as `SEARXNG_URL` | Where *your browser* reaches SearXNG. Only used for links (Open search, Preferences). |
| `SEARXNG_CONTAINER` | `searxng` | Container to inspect, tail, restart and update. |
| `SEARXNG_SETTINGS` | `/searxng/settings.yml` | SearXNG's `settings.yml` inside this container. Mount the same directory SearXNG uses for `/etc/searxng`, read-write. |
| `UPDATE_METHOD` | `docker` | `docker`: pull + recreate via the Docker API. `agent`: queue jobs for a host script ([UNRAID.md](UNRAID.md)). `none`: report only. |
| `UPDATE_LOG` | `$DATA_DIR/update.log` | Log shown on the Updates page. In agent mode point it at the host script's log. |
| `CONTROL_PASSWORD` | — | Enables HTTP basic auth for everything except `/healthz`. |
| `CONTROL_USER` | `admin` | Basic-auth user name. |
| `INSTANCE_LABEL` | — | Short label under the logo. Defaults to the SearXNG host name. |
| `NOTIFY_HOST` | `0` | Agent mode: turn host notifications (Unraid notify) on by default. |
| `DATA_DIR` | `/data` | SQLite history, settings backups, agent queue. Mount a volume here. |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Docker API socket. |
| `ENABLE_DOCKER` | `1` | `0` disables Docker features (logs, restarts, updates, engine catalog). |
| `HOST` / `PORT` | `0.0.0.0` / `8890` | Listen address. |
| `METRICS_INTERVAL` | `60` | Seconds between `/metrics` scrapes. |
| `STATUS_INTERVAL` | `30` | Seconds between health/inspect checks. |
| `UPSTREAM_INTERVAL` | `3600` | Seconds between Docker Hub/GitHub checks. |
| `RETENTION_DAYS` | `30` | History retention. |
| `GITHUB_TOKEN` | — | Optional; raises GitHub's anonymous 60 requests/hour limit. |
| `SEARXNG_IMAGE_REPO` / `SEARXNG_GITHUB_REPO` | `searxng/searxng` | Upstream image and repository to track. |
| `TZ` | UTC | Time zone for log timestamps. |

## SearXNG requirements

```yaml
general:
  enable_metrics: true
  open_metrics: "some-random-string"    # password for /metrics; the panel reads it from settings.yml
search:
  formats: [html, json]                 # json needed for probes and engine tests
```

[`examples/searxng/settings.yml`](../examples/searxng/settings.yml) is a complete starting point with an engine
mix that holds up well against blocking.

## Private (token-gated) engines

Marking an engine *private* adds a `tokens:` entry to it in `settings.yml`. SearXNG then only uses that engine
for requests carrying the token. Browsers get it by saving it once under SearXNG **Preferences → General →
Engine tokens**. API clients (AI tools) and the panel's canary probes don't send it, so metered APIs like the
Brave Search API only serve your own searches. The token is shown with a copy button on the Engines page.

## Notifications

- **ntfy**: topic URL and optional access token on the Alerts page.
- **Host notifications**: agent mode only (e.g. Unraid's notification system); see [UNRAID.md](UNRAID.md).
- The minimum severity, "notify when resolved" and "notify me when SearXNG is updated" options are on the
  Alerts and Updates pages.
