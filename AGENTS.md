# Smart Plant project guidance

## Scope and architecture

- This is `flowcool/Smart_Plant`, a fork of `JGAguado/Smart_Plant`; active work
  targets branch `V2R1`.
- Eight ESP32-S2 devices compose the shared
  `examples/multi-device/packages/smart_plant_core.yaml` package with
  `smart_plant_profile_mqtt.yaml`. Device files contain substitutions only and
  fetch both packages from GitHub `@V2R1`.
- Devices measure AHT20 temperature/humidity, VEML7700 light, capacitive soil
  moisture, and MAX17048 battery state through ESPHome's `max17043` component,
  update a Waveshare 2.9-inch e-paper display once, then deep-sleep for one hour.
- MQTT is the Home Assistant data path; retained values remain visible during
  sleep. The native API exists for Device Builder metadata and awake-window
  runtime logs only. Do not add the devices to HA through the ESPHome
  integration because that duplicates MQTT entities.
- All eight devices use their already-effective `<device_name>-<mac6>` value as
  explicit `configured_name` with `name_add_mac_suffix: false`. This preserves
  every hostname and MQTT prefix byte-for-byte while giving Device Builder and
  build artifacts an unambiguous configured name. DELIVERED 2026-09-03
  (evidence in `infra-zdxz`): explicit `configured_name` +
  `name_add_mac_suffix: false`, `display_name` the single human source. HA
  registry migrated in place (clean MAC-bearing entity_ids, orphan rows/stats
  deleted, retained discovery emptied, consumers re-pointed). `name_by_user` is
  KEPT to preserve FR typography (ASCII-hyphen firmware `friendly_name` would
  downgrade it). Epics `infra-zdxz` + HA `infra-kl21` closed 2026-09-04.
- The authoritative device inventory is in `examples/multi-device/plants.yaml`;
  OTA workflow is in `examples/multi-device/README.md` and `CLAUDE.md`.
- Field map and traps: `docs/naming.md`. Migration contract (executed 2026-09-03,
  Path 2 — no history remap): `docs/naming-architecture.md`. Read both before
  renaming anything; identity fields above are separate from display.

## Live systems and safety

- Live ESPHome configuration is on the NAS at
  `/volume1/docker/homeassistant/esphome/`; HA configuration is at
  `/volume1/docker/homeassistant/homeassistant/`.
- NAS access is read-only unless Florent explicitly authorizes a write, cache
  purge, compile, upload, or flash.
- Validate exactly one canary before any fleet rollout. Never infer successful
  deployment from Device Builder's stored `deployed_config_hash` alone: an ESP32
  may have rolled back after that metadata was recorded.
- Confirm the running version in HA and inspect device runtime logs for rollback
  messages. Device Builder container logs do not include every firmware log.
- A device that reports `Bootloader too old for OTA rollback` needs one serial
  USB flash of `firmware.factory.bin`; OTA does not update the bootloader.
- ESPHome `>=2026.8.0` natively confirms the app image on every orderly
  `deep_sleep.enter`, covering the normal cycle that finishes before ESPHome's
  default 60-second OTA validation window, so production packages no longer call
  `safe_mode.mark_successful` (retired in `infra-3rr.47`; the public
  `configuration.yaml` example keeps it for version-agnostic safety).
- Rollback for shared-package changes: revert the corrective commit, push
  `V2R1`, purge the package cache, and flash the last validated factory/OTA
  image. USB recovery is the final fallback.

## Validation and operations

- Parse changed YAML and run `git diff --check`; inspect both `git diff
  --numstat` and the semantic diff before committing.
- Compile a real canary with the production ESPHome version after purging the
  GitHub package cache. Compilation alone is not deployment evidence.
- Start compiles through the Device Builder firmware API (normally via
  `scripts/esphome_fleet_update.py`), which schedules work on its paired build
  servers, including the VPS. Do not run `esphome compile` directly inside the
  NAS container: that bypasses distributed scheduling and consumes NAS CPU.
- After flash, verify: no OTA rollback log, expected running ESPHome version,
  one short online measurement window, deep sleep, and at least two subsequent
  hourly wake/sleep cycles.
- OTA reachability: `nc -z -w1 <ip> 3232`; ICMP ping is not authoritative.
- Next device wake time: take MAX(`last_updated`/`last_reported`) across ALL of a
  device's HA entities (soil/lux/RSSI change every wake), then add the cycle
  length — 1h normally, 24h when its retained `<prefix>/status/storage_mode` is
  ON. Do NOT use the battery sensor alone: HA does not bump `last_updated` on an
  identical MQTT payload, so a slowly-changing battery % freezes it and the +1h
  prediction lands in the past (observed 2026-09-22, `infra-3rr.53`). Do NOT use
  MQTT `%I` (delivery time, not publish time).
  ```bash
  curl -s "$HASS_SERVER/api/states" -H "Authorization: Bearer $HASS_TOKEN" \
    | python3 -c "import json,sys; ..."
  ```
- Package cache purge: `python3 scripts/esphome_fleet_update.py reset` purges
  every builder (NAS + paired VPS receiver, which runs all compiles). The
  NAS-only `docker exec esphome rm -rf /config/.esphome/packages/` is
  insufficient; see `examples/multi-device/README.md` rollout step 1.
- OTA upload: `docker exec esphome esphome upload /config/<device>.yaml
  --device <ip>`.
- Maintenance uses retained `<prefix>/cmd/maintenance` and
  `<prefix>/status/maintenance`; publish commands retained at QoS 1. See
  `examples/multi-device/README.md`.

## Durable work state

Beads is authoritative for current work: `bd list --metadata-field project=Smart_Plant`.
This section holds only structural pointers (epics, plan docs, durable design facts).
It never records live state: issue status lives in Beads, and per-device firmware
version/config hash live on the devices. Read them from the source every time:
`python3 scripts/esphome_fleet_update.py status` (expected vs deployed hash) and
`scripts/mqtt_retained.sh '+/sensor/esphome_version/state'` (runtime version + config hash).

- Roadmap epic: `infra-3rr`.
- **Delivered** (detail in Beads):
  - Low-battery protective hibernation + e-paper signalling — `infra-3rr.25` (closed
    2026-09-01). WARN <30% full-screen inversion; CRITIQUE <=15% 24h hibernation with
    hysteresis exit >=22%; thresholds per-device. Durable design on the epic.
  - Transport decoupling + package cutover — `infra-3rr.34`, `.36`/`.37`. Prod composes
    `smart_plant_core` + `smart_plant_profile_mqtt` (`_profile_api` = native-API
    alternative; `smart_plant_base` retired). Plan `docs/transport-decoupling-plan.md`.
  - Naming decoupling — epic `infra-zdxz` + HA `infra-kl21` (closed 2026-09-04). Explicit
    `<device_name>-<mac6>` identities, `display_name` the human source, function-only MQTT
    entity names, `name_by_user` kept (FR typography). Field map `docs/naming.md`; contract
    `docs/naming-architecture.md`. HA migration `infra-b5q` (project=homeassistant, closed).
  - Source-audit remediation — epic `infra-3rr.44` (closed 2026-09-16, 12/12 children).
  - Soil calibration — `infra-3rr.44.1` (closed). Durable facts: shared `soil_v_wet = 1.36 V`
    (NOT per-device — inter-device spread <10 mV < intra-device noise 8-16 mV); `soil_v_dry`
    = 2.8 (documented out-of-range); soil split into `Soil Voltage` (diagnostic, acquisition
    source) + `Soil Moisture` (%). TRAP: the generated `metadata:` `soil_v_wet` substitution
    OVERRIDES the core default (same mechanism as per-device names) — purge the package cache
    before compile.
  - MAX17048 low-power doc correction — `infra-3rr.44.12` (closed 2026-09-16).
- **Deferred / gated**:
  - Fork upstreaming — current contribution plan `docs/upstreaming-strategy.md`
    (`infra-3rr.26`); maintainer architecture gate `infra-3rr.21`; preparation
    work is tracked by the roadmap children rather than this file.
  - MAX17048 native model — gate `infra-3rr.45` (defer 2026-10-15) on ESPHome PR #18594
    reaching a stable release; implementation `infra-3rr.46` hard-blocked until then.
  - `safe_mode.mark_successful` retired from `smart_plant_core.yaml` — `infra-3rr.47`
    (native `>=2026.8.0` guard); the public `configuration.yaml` example keeps the
    defensive call. Compile/explicit-IP upload split — `infra-3rr.27`.
- **OTA**: Device Builder push only (`ota: platform: esphome` + `scripts/esphome_fleet_update.py`,
  maintenance-window gated by `ota_min_battery`). Pull-OTA removed 2026-09-03 (`infra-3rr.42`)
  as over-engineered for 8 devices. Historical eval `docs/pull-ota-eval.md` (`infra-3rr.22`).
- Do NOT repeat already-validated flows (Maintenance/Storage entry/exit, naming migration,
  fleet rollout, hourly cycles). `infra-3rr.14` closed wontfix — no live induced-failure
  canaries on a stable fleet (low-battery reject observed live 2026-09-13 anyway).
- Fleet ESPHome version: read from the runtime surfaces above, not legacy retained
  orphans; the `config hash` proves a package revision — see the `esphome-yaml` rule.
