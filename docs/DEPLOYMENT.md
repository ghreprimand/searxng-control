# Deployment

SearXNG Control runs as a container next to your SearXNG container. It needs three things:

1. **Network access to SearXNG** (`SEARXNG_URL`).
2. **SearXNG's `settings.yml`**, mounted read-write (`SEARXNG_SETTINGS`), so it can read the metrics password
   and apply changes.
3. **The Docker socket**, so it can read SearXNG's logs, restart it, and update it.

## 1. New install with Docker Compose

```sh
mkdir searxng-stack && cd searxng-stack
curl -fsSLO https://raw.githubusercontent.com/ghreprimand/searxng-control/main/examples/docker-compose.yml
mkdir searxng && curl -fsSL -o searxng/settings.yml \
  https://raw.githubusercontent.com/ghreprimand/searxng-control/main/examples/searxng/settings.yml
sed -i "s/change-me-metrics-password/$(openssl rand -hex 16)/; s/\"change-me\"/\"$(openssl rand -hex 32)\"/" searxng/settings.yml
docker compose up -d
```

- SearXNG: <http://localhost:8080>
- SearXNG Control: <http://localhost:8890>

The Overview page shows a **Finish setup** box if anything is missing.

## 2. Adding it to an existing SearXNG

Add this service to the compose project that runs SearXNG (or translate it to `docker run`):

```yaml
  searxng-control:
    image: ghcr.io/ghreprimand/searxng-control:latest
    container_name: searxng-control
    restart: unless-stopped
    ports:
      - "127.0.0.1:8890:8890"
    environment:
      SEARXNG_URL: http://searxng:8080          # service/container name of your SearXNG
      SEARXNG_PUBLIC_URL: https://search.example.com
      SEARXNG_CONTAINER: searxng
      SEARXNG_SETTINGS: /searxng/settings.yml
    volumes:
      - ./searxng:/searxng                      # the directory you mount as /etc/searxng in SearXNG
      - control-data:/data
      - /var/run/docker.sock:/var/run/docker.sock
```

Then make sure SearXNG's `settings.yml` contains:

```yaml
general:
  enable_metrics: true
  open_metrics: "<random string>"
search:
  formats: [html, json]
```

The official [searxng-docker](https://github.com/searxng/searxng-docker) setup mounts `./core-config` as
`/etc/searxng`. In that case mount `./core-config:/searxng` and use `SEARXNG_URL=http://core:8080` (or
whatever its service is called).

**Running SearXNG outside Docker?** Set `ENABLE_DOCKER=0` and `UPDATE_METHOD=none`. Monitoring through
metrics, probes and alerts, plus the settings editor, still work. Log-based block detection, restarts after
applying changes, and updates don't. You'd restart SearXNG yourself after applying.

## 3. Unraid

See [UNRAID.md](UNRAID.md). There's a container template, and an optional host agent for Unraid-native updates
and notifications.

## Reaching it from other devices

SearXNG Control can change SearXNG's configuration and recreate containers. **Don't expose it to the
internet.** Good options:

- **Tailscale:** keep the port on localhost and publish it to your tailnet only:

  ```sh
  tailscale serve --bg --https=8444 http://127.0.0.1:8890
  ```

  (and `tailscale serve --bg --https=8443 http://127.0.0.1:8080` for SearXNG itself). The panel shows the
  Tailscale user it sees in the sidebar.
- **LAN only:** bind to the LAN address (`"192.168.1.10:8890:8890"`) and set `CONTROL_PASSWORD`.
- **Reverse proxy with authentication**, e.g. Caddy:

  ```
  control.example.com {
      basic_auth { admin <bcrypt hash from `caddy hash-password`> }
      reverse_proxy 127.0.0.1:8890
  }
  ```

  Disable response buffering if your proxy has it, because the live views use Server-Sent Events.

## Updating

- **SearXNG** is updated by SearXNG Control itself: Updates page → *Automatic updates* (default *Always*,
  at most every 6 h, immediately for fixes to engines that are failing for you) or *Update SearXNG now*.
- **SearXNG Control** is a normal container: `docker compose pull searxng-control && docker compose up -d
  searxng-control` (or let Watchtower etc. handle it). History and settings backups live in `/data`.

## Backups

Everything worth keeping is in `/data` (SQLite history, `backups/` of every `settings.yml` version it applied)
plus SearXNG's own config directory.
