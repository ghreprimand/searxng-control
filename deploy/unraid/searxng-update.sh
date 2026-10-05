#!/bin/bash
#description=Daily: pull searxng/searxng:latest, rebuild the container if the image changed, roll back if it fails its health check.
#arrayStarted=true
# Upstream ships several builds a day, mostly engine-parser fixes for new
# anti-bot measures; a stale image is the #1 cause of "every engine is broken".
set -u
NAME=${NAME:-searxng}
URL=${URL:-http://127.0.0.1:8080}   # SearXNG as reachable from the Unraid host
REPO=searxng/searxng
REBUILD=/usr/local/emhttp/plugins/dynamix.docker.manager/scripts/rebuild_container
NOTIFY=/usr/local/emhttp/webGui/scripts/notify
LOG=${LOG:-/mnt/user/appdata/searxng/update.log}
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

healthy() {
  for _ in $(seq 1 45); do
    if curl -fsS -m 3 "$URL/healthz" >/dev/null 2>&1 \
       && curl -fsS -m 20 "$URL/search?q=wikipedia&format=json" | jq -e '.results|length>0' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

running=$(docker inspect -f '{{.Image}}' "$NAME" 2>/dev/null || true)
if ! docker pull -q "$REPO:latest" >/dev/null 2>&1; then
  log "pull failed (network/registry?) - keeping current image"; exit 0
fi
latest=$(docker image inspect -f '{{.Id}}' "$REPO:latest")
if [ -n "$running" ] && [ "$running" = "$latest" ]; then
  log "up to date ($(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$REPO:latest"))"; exit 0
fi

[ -n "$running" ] && docker tag "$running" "$REPO:rollback"
ver=$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$REPO:latest")
log "updating to $ver"
"$REBUILD" "$NAME" >/dev/null 2>&1
if healthy; then
  log "update OK ($ver)"
  docker image prune -f >/dev/null 2>&1
  exit 0
fi

log "new image unhealthy - rolling back"
if docker image inspect "$REPO:rollback" >/dev/null 2>&1; then
  docker tag "$REPO:rollback" "$REPO:latest"
  "$REBUILD" "$NAME" >/dev/null 2>&1
  healthy && log "rollback OK" || log "rollback ALSO unhealthy"
fi
"$NOTIFY" -e "SearXNG" -s "SearXNG update failed" -d "Image $ver failed its health check; rolled back. See $LOG" -i warning
