# Smart Plant — Claude entry point

Read and follow `AGENTS.md` first. It is the canonical project architecture,
safety, validation, and current-work guide shared by coding agents.

# Claude-specific context

Fork `flowcool/Smart_Plant` of `JGAguado/Smart_Plant`. Active branch: `V2R1`.
Upstream PRs: #9,#12,#13,#17,#18,#19,#20,#22,#25 merged on `upstream/V2R1`
(the integration branch, 105 commits ahead of `upstream/main`). #25 is the
ESPHome 2027.1.0 image `platform:` syntax; we made the same fix independently
(convergent, trivial rebase). Fork upstreaming strategy + coupling audit:
`docs/upstreaming-strategy.md` (infra-3rr.26).

## Architecture

- 8 ESP32-S2 devices in production, deep sleep 1h cycle
- **Data path**: MQTT-only (retained values survive sleep, no "unavailable" in HA)
- **Native API**: enabled for ESPHome dashboard metadata only (mDNS `_esphomelib._tcp`) — do NOT add to HA via ESPHome integration (duplicate entities)
- **Package system**: `smart_plant_core.yaml` contains transport-agnostic shared logic; production device files compose it with `smart_plant_profile_mqtt.yaml` and otherwise contain substitutions only
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
Unique species keep the core default `name_add_mac_suffix: true`, which appends
the last 3 MAC bytes to produce a unique hostname and MQTT topic prefix.
Duplicate species (the two Ceropegia woodii) share one `device_name`, so they
instead set an explicit unique `configured_name` (`<device_name>-<mac6>`) with
`name_add_mac_suffix: false`; the ESPHome node name, hostname and MQTT prefix
are then taken verbatim from `configured_name`, avoiding a Device Builder
collision on identical node names. Device YAML filenames match `device_name`
(without MAC).

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

## Durable work state

All tasks tracked via `bd` (beads). Use `bd memories smartplant` for persistent
knowledge. Ready/in-progress issue status is injected dynamically by the
SessionStart hook — do not duplicate tactical status here.

Structural pointers (epics, plan docs, cross-project handoffs):

- Roadmap epic: `infra-3rr` (post-baseline: durability, validation, OTA, upstream).
- Naming epic: `infra-zdxz` — decouple technical identity / human display name /
  MQTT entity naming. Cross-project HA registry migration (in-place unique_id):
  `infra-kl21` (`project=homeassistant`). Current-state field map:
  `docs/naming.md`.
- Package cutover (`infra-3rr.36`/`.37`) and low-battery hibernation
  (`infra-3rr.25`) shipped fleet-wide (8/8 on `core`+`profile_mqtt`);
  `smart_plant_base.yaml` retired.
- Pull-OTA opt-in (`infra-3rr.23`): shipped in base package, inert until a
  device sets `pull_ota_manifest_url` and flips "Pull OTA" ON in HA.
- Historical naming migration woodii→botanical: `infra-b5q`
  (`project=homeassistant`, closed) — do not restore legacy prefixes.
- Upstreaming strategy + coupling audit: `docs/upstreaming-strategy.md`
  (`infra-3rr.26`).
