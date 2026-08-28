# Smart Plant project guidance

## Scope and architecture

- This is `flowcool/Smart_Plant`, a fork of `JGAguado/Smart_Plant`; active work
  targets branch `V2R1`.
- Eight ESP32-S2 devices use the shared
  `examples/multi-device/packages/smart_plant_base.yaml` package. Device files
  contain substitutions only and fetch the package from GitHub `@V2R1`.
- Devices measure AHT20 temperature/humidity, VEML7700 light, capacitive soil
  moisture, and MAX17043 battery state, update a Waveshare 2.9-inch e-paper
  display once, then deep-sleep for one hour.
- MQTT is the Home Assistant data path; retained values remain visible during
  sleep. The native API exists for Device Builder metadata and awake-window
  runtime logs only. Do not add the devices to HA through the ESPHome
  integration because that duplicates MQTT entities.
- MQTT topic prefixes are auto-derived by ESPHome (`name_add_mac_suffix: true`)
  from `device_name` + last 3 MAC bytes. Device YAML files set only the
  botanical `device_name`; the MAC suffix is appended automatically. Two
  Ceropegias migrated from legacy sequential prefixes (`woodii1`/`woodii2`) to
  auto-derived MAC-only prefixes. The coordinated migration is complete across
  ESPHome, MQTT, Home Assistant entity references, dashboards, and Plant
  integration bindings; evidence is recorded in Home Assistant epic
  `infra-b5q`.
- The authoritative device inventory is in `examples/multi-device/plants.yaml`;
  OTA workflow is in `examples/multi-device/README.md` and `CLAUDE.md`.

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
- Every orderly sleep path must call `safe_mode.mark_successful` before
  `deep_sleep.enter`, because the normal cycle can finish before ESPHome's
  default 60-second OTA validation window.
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
- Package cache purge: `docker exec esphome rm -rf
  /config/.esphome/packages/`.
- OTA upload: `docker exec esphome esphome upload /config/<device>.yaml
  --device <ip>`.
- Maintenance uses retained `<prefix>/cmd/maintenance` and
  `<prefix>/status/maintenance`; publish commands retained at QoS 1. See
  `examples/multi-device/README.md`.

## Durable work state

- Beads is authoritative for current work. Filter with
  `bd list --metadata-field project=Smart_Plant`.
- Roadmap epic: `infra-3rr`.
- Low-battery protective hibernation + e-paper signalling: epic `infra-3rr.25`
  (gatekeeper molecule — RTFM `.25.1/.2/.3` block impl `.25.4`, then
  config-validate `.25.5`, bench `.25.6/.7/.8`, human-gate rollout `.25.9`).
  Ready frontier is the three RTFM tasks; nothing codes before they close.
  Approved design is a session plan artifact; the durable design lives on the
  epic. Adds WARN (<30%) full-screen e-paper inversion and CRITIQUE (<=15%) 24h
  protective hibernation with hysteresis exit (>=22%), thresholds per-device.
- Residual induced-failure validation only: `infra-3rr.14` (low-battery
  rejection, repeated-ON deadline restart, MQTT outage/recovery, and failed-OTA
  retry). Normal Maintenance, Storage entry/daily wake/exit, naming migration,
  fleet rollout, and hourly cycles are already validated; do not repeat them.
- Home Assistant naming migration: `infra-b5q` with `project=homeassistant`
  (closed and validated across all eight active MQTT devices).
- Pull-based OTA: shipped in `smart_plant_base.yaml` on V2R1@24fea64
  (`infra-3rr.23`). Every device carries the `http_request`, `ota:
  platform: http_request`, `update: platform: http_request`
  (`pull_ota_update`), and native template switch `pull_ota_enabled`
  (RESTORE_DEFAULT_OFF, entity_category config). Default is inert:
  `pull_ota_manifest_url` = RFC 5737 `http://192.0.2.1/manifest.json`
  placeholder and the switch defaults OFF, so `decide_sleep` never calls
  `update.check`. To opt in on a device: publish an ESP-Web-Tools manifest,
  override `pull_ota_manifest_url` in the device YAML, and turn the "Pull
  OTA" switch ON in Home Assistant. During the next maintenance window
  `decide_sleep` calls `update.check`; if the manifest advertises a newer
  `esphome.project.version`, the `on_update_available` handler publishes
  `OTA_PULL_STARTING` (text_sensor + retained MQTT) and invokes
  `update.perform`. The Device Builder push path remains available in
  parallel. Evaluation doc: `docs/pull-ota-eval.md` (`infra-3rr.22`).
