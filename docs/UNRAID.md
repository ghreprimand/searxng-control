# Unraid

## Basic install (built-in updater)

1. Install SearXNG (e.g. the `searxng/searxng` image) with its config folder at `/mnt/user/appdata/searxng`.
   In its `settings.yml` set `general.open_metrics` to a random string and include `json` in
   `search.formats` (see [CONFIGURATION.md](CONFIGURATION.md)).
2. Copy [`deploy/unraid/searxng-control.xml`](../deploy/unraid/searxng-control.xml) to
   `/boot/config/plugins/dockerMan/templates-user/my-searxng-control.xml`, then in the Docker tab click
   *Add Container* and pick **searxng-control**.
3. Check the template values:
   - `SEARXNG_URL` must reach SearXNG from the container. `http://172.17.0.1:8080` is the Unraid host as seen
     from the default bridge network.
   - The *SearXNG appdata* path must be the folder SearXNG mounts as `/etc/searxng`.
4. Open `http://<unraid-ip>:8890/`.

With `UPDATE_METHOD=docker` (the default), updates recreate the SearXNG container through the Docker API with
the same settings. The Unraid UI keeps showing it normally.

## Optional: host agent (Unraid-native updates + Unraid notifications)

If you'd rather have updates go through Unraid's own `rebuild_container`, so the container is rebuilt from its
template, and get alerts as Unraid notifications:

1. Copy `deploy/unraid/host-agent.sh` and `deploy/unraid/searxng-update.sh` to
   `/mnt/user/appdata/searxng-control/` and make them executable.
2. In *Settings → User Scripts* add a script that runs every minute (custom schedule `* * * * *`):

   ```bash
   #!/bin/bash
   exec /mnt/user/appdata/searxng-control/host-agent.sh
   ```

   Optionally add a second, daily script that runs `searxng-update.sh` directly as a backstop.
3. On the searxng-control container set:
   - `UPDATE_METHOD=agent`
   - `UPDATE_LOG=/searxng/update.log` (the update script logs to `/mnt/user/appdata/searxng/update.log` by
     default)
   - `NOTIFY_HOST=1`

The Updates page shows the agent's heartbeat. If it stops checking in, the *agent_stale* alert fires.

`searxng-update.sh` pulls `searxng/searxng:latest` and runs `rebuild_container searxng` when the image changed.
It then checks `/healthz` plus a real search. If they fail, it retags the previous image and rebuilds again
(rollback) and raises an Unraid notification.
