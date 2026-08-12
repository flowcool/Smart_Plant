# Smart Plant — Claude entry point

Read and follow `AGENTS.md` first. It is the canonical project architecture,
safety, validation, and current-work guide shared by coding agents.

# Claude-specific context

Fork `flowcool/Smart_Plant` of `JGAguado/Smart_Plant`. Active branch: `V2R1`.
Upstream PRs: #9,#12,#13,#17,#18,#19,#20 merged. PR #22 (multi-device packages) open.

## Architecture

- 8 ESP32-S2 devices in production, deep sleep 1h cycle
- **Data path**: MQTT-only (retained values survive sleep, no "unavailable" in HA)
- **Native API**: enabled for ESPHome dashboard metadata only (mDNS `_esphomelib._tcp`) — do NOT add to HA via ESPHome integration (duplicate entities)
- **Package system**: `smart_plant_base.yaml` = all shared logic; device files = substitutions only + `packages: base: github://flowcool/Smart_Plant/...@V2R1`
- `display_lambda.h` exists with extracted C++ helpers but is NOT yet wired in (inline lambda still in base YAML)
- Sensors: AHT20 (temp/humidity), VEML7700 (lux), ADC soil moisture, MAX17043 (battery)
- Display: Waveshare 2.9" e-paper (2.90inv2), full refresh every wake

## NAS (source of truth for live configs)

- ESPHome configs: `/volume1/docker/homeassistant/esphome/`
- HA configs: `/volume1/docker/homeassistant/homeassistant/`
- Plant label images: `/volume1/docker/homeassistant/esphome/plant_labels/`
- **Read-only by default** — write only on explicit user confirmation

## Device inventory

`examples/multi-device/plants.yaml` is the keyed repository identity registry
for the eight deployed plants. It records immutable device names and MQTT
prefixes, French display names, botanical labels, IPs, label images, timezone,
and calibration status. Live ESPHome files remain authoritative for credentials
and runtime configuration.

MQTT prefixes include the historical MAC suffix and must never change. The
shared `1.25V → 100%, 2.8V → 0%` soil values are defaults; they are not evidence
of individual probe calibration.

## Operations

- **OTA detection**: `nc -z -w1 <ip> 3232` (ICMP ping unreliable on ESP32)
- **Flash CLI**: `docker exec esphome esphome upload /config/<device>.yaml --device <ip>`
- **Package cache clear**: `docker exec esphome rm -rf /config/.esphome/packages/` after GitHub push
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

## Rules

| Rule | Scope | Purpose |
|---|---|---|
| `esphome-yaml` | `*.yaml` | ESPHome YAML conventions, native capability check before adding entities |
| `nas-operations` | always | NAS RO default, OTA safety, rollback-before-continue |

## Task tracking

All tasks tracked via `bd` (beads). Use `bd memories smartplant` for persistent knowledge.
Roadmap epic: `infra-3rr` (HA wake action, partial e-paper, ESP32-C6 eval, soil sensor eval).
