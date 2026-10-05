#!/bin/bash
# SearXNG Control host agent for Unraid (UPDATE_METHOD=agent).
# Run every minute as a User Script. See docs/UNRAID.md.
#
# The container drops JSON jobs in $QUEUE/pending/; this script runs them and
# writes results to $QUEUE/done/.
#   {"action":"update"}                                                 -> $UPDATE_SCRIPT
#   {"action":"notify","subject":..,"description":..,"importance":..}  -> Unraid notify
set -u
APPDATA=${APPDATA:-/mnt/user/appdata/searxng-control}
QUEUE=${QUEUE:-$APPDATA/queue}
UPDATE_SCRIPT=${UPDATE_SCRIPT:-$APPDATA/searxng-update.sh}
NOTIFY=/usr/local/emhttp/webGui/scripts/notify

exec 9>/tmp/searxng-control-agent.lock
flock -n 9 || exit 0
mkdir -p "$QUEUE/pending" "$QUEUE/done"
date +%s > "$QUEUE/agent-heartbeat"

for f in "$QUEUE"/pending/*.json; do
  [ -e "$f" ] || break
  id=$(basename "$f" .json)
  action=$(jq -r '.action // empty' "$f" 2>/dev/null)
  rc=0
  case "$action" in
    update)
      out=$("$UPDATE_SCRIPT" 2>&1) || rc=$?
      ;;
    notify)
      out=$("$NOTIFY" -e "SearXNG Control" \
        -s "$(jq -r '.subject // "SearXNG"' "$f")" \
        -d "$(jq -r '.description // ""' "$f")" \
        -i "$(jq -r '.importance // "normal"' "$f")" 2>&1) || rc=$?
      out=${out:-sent}
      ;;
    *)
      rc=2; out="unknown action: $action"
      ;;
  esac
  jq -n --slurpfile req "$f" --arg out "$out" --argjson rc "$rc" --arg finished "$(date -Iseconds)" \
    '{request: $req[0], rc: $rc, output: $out, finished: $finished}' > "$QUEUE/done/$id.json.tmp" \
    && mv "$QUEUE/done/$id.json.tmp" "$QUEUE/done/$id.json"
  rm -f "$f"
done
find "$QUEUE/done" -type f -name '*.json' -mtime +14 -delete 2>/dev/null
exit 0
