#!/usr/bin/env bash
# Read-only dump of RETAINED MQTT topics for the Smart_Plant fleet.
#
# Why this exists: verifying deployed fleet state (ESPHome version, maintenance/
# storage switches, LWT) means reading retained MQTT. The broker requires auth,
# and renamed entities leave STALE retained orphans that misreport state — e.g. a
# legacy <prefix>/sensor/<device>_esphome_version/state showed 2026.7.4 while the
# live firmware was 2026.8.2. Authoritative version = the HA discovery config
# dev.sw field, or the CURRENT function-only topic <mac-prefix>/sensor/
# esphome_version/state, cross-checked with esphome/discover/<current-mac-name>.
# See `bd memories version-check` and infra-3rr.49 (orphan cleanup).
#
# Read-only: subscribes only, never publishes.
#
# Usage:
#   scripts/mqtt_retained.sh                                  # all retained topics
#   scripts/mqtt_retained.sh 'cyperus-papyrus-54a9b2/#'
#   scripts/mqtt_retained.sh '#' | grep -E '/sensor/esphome_version/state'
#
# Credentials: MQTT_USER/MQTT_PASS env override, else read from the HA config
# entry (HA_STORAGE, default the local homeassistant project clone). SSH_HOST and
# MQTT_CONTAINER default to the production broker host/container.
set -euo pipefail

TOPIC="${1:-#}"
SSH_HOST="${SSH_HOST:-ugreen}"
MQTT_CONTAINER="${MQTT_CONTAINER:-mqtt}"
WAIT="${MQTT_WAIT:-6}"
HA_STORAGE="${HA_STORAGE:-/home/flow/claude_project/homeassistant/.storage/core.config_entries}"

MQTT_USER="${MQTT_USER:-}"
MQTT_PASS="${MQTT_PASS:-}"
if [[ -z "$MQTT_USER" || -z "$MQTT_PASS" ]]; then
  if [[ ! -r "$HA_STORAGE" ]]; then
    echo "mqtt_retained: set MQTT_USER/MQTT_PASS, or make HA_STORAGE readable: $HA_STORAGE" >&2
    exit 2
  fi
  # Extract broker user/password from the HA MQTT config entry (read-only).
  read -r MQTT_USER MQTT_PASS < <(python3 - "$HA_STORAGE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
e = next(x for x in d["data"]["entries"] if x.get("domain") == "mqtt")
print(e["data"]["username"], e["data"]["password"])
PY
)
fi

# Password expands at runtime into the remote command (broker auth needs it as an
# arg); it is never a literal in this file. On the single-operator NAS the brief
# argv exposure is acceptable; override with MQTT_PASS to avoid the HA_STORAGE read.
exec ssh "$SSH_HOST" \
  "/usr/bin/docker exec '$MQTT_CONTAINER' mosquitto_sub -h localhost \
   -u '$MQTT_USER' -P '$MQTT_PASS' -t '$TOPIC' -v -W '$WAIT'"
