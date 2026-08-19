# Smart Plant — Claude entry point

Read and follow `AGENTS.md` first. It is the canonical project architecture,
safety, validation, and current-work guide shared by coding agents.

# Claude-specific context

Fork `flowcool/Smart_Plant` of `JGAguado/Smart_Plant`. Active branch: `V2R1`.
Upstream PRs: #9,#12,#13,#17,#18,#19,#20,#22 merged. PR #23 (ESPHome
2027.1.0 image syntax) open.

## Architecture

- 8 ESP32-S2 devices in production, deep sleep 1h cycle
- **Data path**: MQTT-only (retained values survive sleep, no "unavailable" in HA)
- **Native API**: enabled for ESPHome dashboard metadata only (mDNS `_esphomelib._tcp`) — do NOT add to HA via ESPHome integration (duplicate entities)
- **Package system**: `smart_plant_base.yaml` = all shared logic; device files = substitutions only + `packages: base: github://flowcool/Smart_Plant/...@V2R1`
- Sensors: AHT20 (temp/humidity), VEML7700 (lux), ADC soil moisture, MAX17043 (battery)
- Display: Waveshare 2.9" e-paper (2.90inv2), full refresh every wake

## NAS (source of truth for live configs)

- ESPHome configs: `/volume1/docker/homeassistant/esphome/`
- HA configs: `/volume1/docker/homeassistant/homeassistant/`
- Plant label images: `/volume1/docker/homeassistant/esphome/plant_labels/`
- **Read-only by default** — write only on explicit user confirmation

## Device inventory

`examples/multi-device/plants.yaml` is the keyed repository identity registry
for the eight deployed plants. It records botanical device names, auto-derived
MQTT topic prefixes, French display names, botanical labels, IPs, label images,
timezone, and calibration status. Live ESPHome files remain authoritative for
credentials and runtime configuration.

Naming convention: `device_name` is the botanical slug (`genre-espece`).
`name_add_mac_suffix: true` in the base package appends the last 3 MAC bytes
automatically, producing the unique hostname and MQTT topic prefix. Duplicate
species (two Ceropegia woodii) share the same `device_name`; the MAC suffix
guarantees uniqueness. Device YAML filenames match `device_name` (without MAC).

The 2026-08-14 migration is complete across ESPHome filenames/configuration,
MQTT retained topics, Home Assistant device/entity registries, automations,
dashboard references, and all eight Plant integration bindings. Home Assistant
epic `infra-b5q` is the authoritative migration evidence. Do not restore the
legacy `woodii1`/`woodii2` prefixes or MAC-suffixed Home Assistant entity IDs.

The shared `1.25V → 100%, 2.8V → 0%` soil values are defaults; they are not
evidence of individual probe calibration.

## Operations

- **OTA detection**: `nc -z -w1 <ip> 3232` (ICMP ping unreliable on ESP32)
- **Flash CLI**: `docker exec esphome esphome upload /config/<device>.yaml --device <ip>`
- **Package cache clear**: `docker exec esphome rm -rf /config/.esphome/packages/` after GitHub push
- **Compile entrypoint**: use the Device Builder firmware API through
  `scripts/esphome_fleet_update.py`; Device Builder owns remote build-server
  selection. Do not invoke `esphome compile` in the NAS container because it
  bypasses the paired VPS builder and runs the cold build locally.
- **Logs**: MQTT logging is disabled, but runtime logs are available through the
  native API while a device is awake. Device Builder container logs are not a
  substitute for device runtime logs when diagnosing OTA rollback.
- **`use_address`**: must be in `wifi:` block of device YAML, not just `substitutions:`
- **Validate 1 device before batch OTA** — confirm runtime version and inspect
  rollback logs; Device Builder's deployed hash can remain stale after rollback.
- **Old bootloader**: `Bootloader too old for OTA rollback` requires one USB
  factory flash. OTA does not update the bootloader.
- **Deep-sleep OTA validation**: keep `safe_mode.mark_successful` before every
  orderly `deep_sleep.enter` path.
- **Pull-OTA (opt-in)**: base package ships `update: platform: http_request`
  (`pull_ota_update`) + native switch `pull_ota_enabled` (default OFF). To
  activate on one device: host an ESP-Web-Tools manifest (JSON with
  `chipFamily/version/ota.md5/ota.path`), set `pull_ota_manifest_url:
  http://<host>/manifest.json` in the device YAML, flip "Pull OTA" ON in HA.
  Next maintenance window pulls the manifest and self-flashes if version
  differs. Device Builder push path stays in parallel. Details in
  `docs/pull-ota-eval.md`.

## Rules

| Rule | Scope | Purpose |
|---|---|---|
| `esphome-yaml` | `*.yaml` | ESPHome YAML conventions, native capability check before adding entities |
| `nas-operations` | always | NAS RO default, OTA safety, rollback-before-continue |

## Task tracking

All tasks tracked via `bd` (beads). Use `bd memories smartplant` for persistent knowledge.
Roadmap epic: `infra-3rr` (HA wake action, partial e-paper, ESP32-C6 eval, soil sensor eval).

Current operational work:

- `infra-3rr.14`: residual induced-failure validation only; completed normal,
  Storage, naming, rollout, and hourly-cycle tests must not be repeated.
- `infra-3rr.21`: coordinate upstream API/MQTT profiles with Smart Plant
  maintainer (open, P2).
- `infra-3rr.23`: pull-OTA shipped in base package (V2R1@fc2cff6), fleet
  mass rollout in progress at last handoff (canary Papyrus verified running
  the new firmware, 7 devices pending flash). Feature is inert until a
  device sets `pull_ota_manifest_url` and flips the "Pull OTA" switch ON
  in HA. Retained `/cmd/maintenance=ON` still published on all 8 devices.
- `infra-b5q` (`project=homeassistant`): closed cross-project naming
  migration evidence, kept as historical pointer.
