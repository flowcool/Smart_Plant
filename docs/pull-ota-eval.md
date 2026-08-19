# Pull-based OTA evaluation — ESPHome `update` component

**Bead**: `infra-3rr.22` (under roadmap `infra-3rr`)
**Date**: 2026-08-19
**Status**: Recommendation — GO for pilot on ONE canary, dual-path with the
Device Builder push retained as fallback. Feature designed as **opt-in for the
upstream community** via a single native HA switch.

> **UPDATE 2026-08-19** — Feature shipped in `smart_plant_base.yaml` on
> `V2R1@24fea64` under `infra-3rr.23`. Canary flash on `cyperus-papyrus-54a9b2`
> passed (running == deployed hash `e16dbfe0`, orderly return to deep sleep,
> `safe_mode.mark_successful` confirmed). Fleet rollout via
> `scripts/esphome_fleet_update.py update all` in progress at time of writing.
> Default is inert (`pull_ota_manifest_url` = RFC 5737 placeholder, switch OFF)
> so no device pulls anything until an operator opts in. `infra-3rr.14` gating
> was dropped by operator decision the same day.
>
> Doc-verified corrections applied vs the initial draft below:
> - `http_request` config key on ESP32 is `buffer_size_rx` (not `buffer_size`).
> - `update.check` / `update.perform` / `update.is_available` take `id:` in
>   mapping form.
> - `on_update_available` trigger on the update entity exists → the manifest
>   handling is event-driven, no timer/delay hack.
> - `update: platform: http_request` validates `source` at parse time; empty
>   string is rejected, hence the RFC 5737 TEST-NET-1 placeholder default.
>

## Context

Current OTA path: Home Assistant flips retained `<prefix>/cmd/maintenance=ON` → the
device catches the retained message at boot, enters maintenance mode
(`deep_sleep.prevent`, `page_maintenance` shown, `status/maintenance=ON` after
the display settle handshake), and stays awake for
`maintenance_timeout_minutes`. Device Builder must then push OTA to the
detected IP within that window.

Two recurring pain points:

1. Wake-window race — Device Builder needs the device IP and a healthy TCP:3232
   in a bounded window; misses require flipping maintenance off/on again.
2. Device Builder's stored "deployed hash" can drift from the running firmware
   after an OTA rollback (documented in `AGENTS.md` / `nas-operations.md`), so
   Device Builder is not authoritative on the actually-running version.

The ESPHome `update` component + `http_request` OTA back-end invert the model:
the device pulls a JSON manifest and flashes itself. The device becomes
authoritative on its own version and no external push is needed.

The upstream maintainer's preferred integration is the ESPHome native API, not
MQTT. Any user-facing control added by this feature must therefore be
**native-API-first**, with MQTT auto-discovery as a free by-product for
deployments (like ours) that run on MQTT.

## How it works (verified from ESPHome docs 2026-08-19)

- `update: platform: http_request` polls a JSON manifest (ESP-Web-Tools schema)
  every `update_interval` (default 6 h). Fields per build: `chipFamily`,
  `version`, `ota.md5`, `ota.path`.
- Actions: `update.check`, `update.perform` (with `force`). Condition:
  `update.is_available`.
- Back-end `ota: platform: http_request` downloads `firmware.ota.bin`, verifies
  MD5, flashes, and **reboots automatically**.
- Exposes an HA `update` entity (installed vs available version, Install button).
- 512-byte HTTP response buffer default; GitHub releases URLs may exceed it →
  serve from GitHub Pages or raise `buffer_size` in `http_request`.

## Fit with Smart Plant base package

Reviewed `examples/multi-device/packages/smart_plant_base.yaml`:

- `esphome.project.name = "smart.plant"`, `project.version = "2.2"` — single
  shared version across the fleet, so one manifest per chip family suffices.
- All eight deployed devices are ESP32-S2 (`chipFamily: "ESP32-S2"`).
- `enter_deep_sleep` script calls `safe_mode.mark_successful` before
  `deep_sleep.enter` on every orderly path (rule enforced in
  `.claude/rules/esphome-yaml.md`).
- Maintenance mode already provides a battery-gated
  (`ota_min_battery = 50`), deep-sleep-prevented, deterministic OTA window.
- `text_sensor: platform: version` diagnostic is retained via MQTT and remains
  authoritative on the running firmware for operator visibility.

The maintenance-mode window is the natural trigger point for `update.perform`,
gated on `pull_ota_enabled && maintenance_active && update.is_available &&
battery >= ota_min_battery`.

## Target design

Components are **always compiled in**. No build-time substitution flag. Per-user
opt-in is one native HA switch, default OFF → zero behavioural change for
anyone who does not touch it. Flash cost of always-on inclusion: +30–80 KB out
of 644 KB free per OTA slot (measured, see Flash budget below) — negligible.

### 1. Native HA kill switch (single point of activation)

```yaml
switch:
  - platform: template
    id: pull_ota_enabled
    name: "Pull OTA"
    icon: mdi:cloud-download-outline
    optimistic: true
    restore_mode: RESTORE_DEFAULT_OFF   # NVS-backed, survives reboot/OTA/sleep
    entity_category: config
```

No `command_topic`/`state_topic` — the switch is protocol-agnostic:

| HA integration | UX | Persistence |
|---|---|---|
| ESPHome API (maintainer default) | First-class native switch on the device | NVS local |
| MQTT auto-discovery (our fleet) | Discovered via `homeassistant/switch/.../config`, retained state | NVS local + retained MQTT state |

The pull-OTA decision is taken **on the device** during the maintenance
window; the switch state does not need to be reachable from HA while the
device sleeps. That is precisely why it can stay MQTT-agnostic, unlike
`maintenance_control` / `storage_mode` which must be retained for our
deep-sleep flow.

### 2. Pull-OTA components

```yaml
http_request:
  buffer_size: 1024   # margin above default 512

ota:
  - platform: esphome
    password: "${ota_password}"
  - platform: http_request

update:
  - platform: http_request
    name: "Firmware pull update"
    source: "${pull_ota_manifest_url}"
    update_interval: never    # driven manually inside maintenance
```

Substitution default in base: `pull_ota_manifest_url: ""`. Users who enable
the switch override it in their device YAML with the URL of their own manifest
(one line). Rationale: no upstream infrastructure to host or maintain,
complete opt-in, each user owns their own binary distribution.

### 3. Runtime gate

Wired into the maintenance-entry branch of `decide_sleep`, after
`maintenance_status = ON` handshake and before `maintenance_watchdog`:

```
if  id(pull_ota_enabled).state
 && id(maintenance_active)
 && id(batpercent).state >= ${ota_min_battery}
 && update.is_available
then  publish "OTA_PULL_STARTING" status
      update.perform
      # device reboots automatically → next boot enters maintenance again
      # via retained topic → completes normal cycle → mark_successful → sleep
```

Any status publish MUST happen before `update.perform` (which reboots) — never
after.

### 4. Coexistence with the existing push path

`ota: platform: esphome` (Device Builder push) stays enabled in parallel.
Users have three independent, complementary paths:

- **Automation via HA MQTT** (existing) → maintenance mode → push from Device
  Builder or ESPHome dashboard. Unchanged.
- **Automation via HA API** (upstream community) → maintenance mode → same push
  path from the ESPHome dashboard. Unchanged.
- **Pull-OTA** (new, opt-in) → HA switch ON → next maintenance window pulls the
  manifest and self-flashes. Ignored if switch is OFF.

Zero cutover risk. Turning the switch OFF at any moment restores full status
quo.

## Manifest generation

Device Builder outputs artifacts under the NAS ESPHome build tree. Path
verified 2026-08-19 on `peperomia-tetraphylla` — build layout is
`.esphome/build/<device>/build/firmware.ota.bin` (not `.pioenvs/…` — that layout
is legacy PlatformIO). Sketch of a post-build hook:

```bash
# On the NAS, run after each Device Builder build of a pilot device
DEV=<device>
BIN="/volume1/docker/homeassistant/esphome/.esphome/build/$DEV/build/firmware.ota.bin"
WEB=/volume1/web/smartplant
VER=$(yq -r '.esphome.project.version // .substitutions.project_version' \
       /volume1/docker/homeassistant/esphome/$DEV.yaml)
MD5=$(md5sum "$BIN" | awk '{print $1}')
cp "$BIN" "$WEB/firmware.ota.bin"
jq -n --arg v "$VER" --arg md5 "$MD5" \
      '{name:"smart.plant", version:$v,
        builds:[{chipFamily:"ESP32-S2",
                 ota:{md5:$md5, path:"firmware.ota.bin"}}]}' \
  > "$WEB/manifest.json"
```

Hook trigger options (pick one during pilot): (a) file-watch on `.esphome/build`,
(b) manual script invoked from the developer workstation after the Device
Builder build completes, (c) Device Builder webhook if it exposes one.

## Flash budget — verified 2026-08-19

Read the partition table from the last built device (`peperomia-tetraphylla`,
ESPHome 2026.7.4, build 2026-08-18) on the NAS:

| Partition | Size | Role |
|---|---|---|
| `app0` | 1792 KB (1.75 MB) | OTA slot A |
| `app1` | 1792 KB (1.75 MB) | OTA slot B |
| nvs | 384 KB | |
| spiffs | 60 KB | |
| otadata / phy_init / eeprom | 16 KB | |

Total 4 MB (Saola-1 default dual-OTA layout).

- Current `firmware.ota.bin` = **1,175,200 bytes = 1.12 MB** → **64%** of a slot.
- **Headroom per slot: ~644 KB free.**
- Estimated added footprint of `http_request` + `ota.http_request` +
  `update.http_request` ≈ 30–80 KB → fits with ~10× safety margin.
- No custom `partition_table` required.

## Open questions to resolve during pilot

1. Confirm `esphome.project.version` in the running firmware matches the
   manifest `version` string byte-for-byte, so `update.check` correctly reports
   "up to date" after a successful pull.
2. Confirm HTTP-only fetch works — no HTTPS certificate handling on ESP32-S2.
3. Order of operations: `update.perform` reboots automatically, so any MQTT /
   API status publish about "OTA started" must happen BEFORE the call.
4. Interaction with `safe_mode.mark_successful` on the first post-flash boot.
   Expectation: new firmware boots, sees retained maintenance topic, runs the
   maintenance cycle, calls `mark_successful` before `deep_sleep.enter` — same
   path as any orderly cycle. Verify with device runtime logs via native API.
5. Behaviour of the `update` entity when `source` is empty or unreachable —
   should stay in `unknown` / `no update` without noisy errors so the default
   OFF path is quiet.

## Rollback

- Canary only. Other seven devices never see the switch flipped and stay 100%
  on the Device Builder push path.
- To revert the canary: `git revert <pilot commit>` on `V2R1`, clear the
  package cache on the NAS
  (`docker exec esphome rm -rf /config/.esphome/packages/`), and push the
  reverted firmware via the existing Device Builder path during the next
  maintenance window.
- Instant runtime disable without a re-flash: flip the `Pull OTA` switch OFF
  from HA. Feature becomes inert immediately; next maintenance window uses the
  push path only.
- No shared state to unwind; the change is additive.

## Go / no-go

**GO**, priority P3, sequenced after `infra-3rr.14` (residual maintenance
failure validation) so the maintenance flow is fully proven before it also
carries the pull-OTA trigger. Follow-up bead (pilot rollout on one canary)
to be created if the pilot open questions all resolve positively.

## Not addressed here

- The **bootloader-too-old** OTA-rollback case remains — pull OTA cannot fix
  it; it still requires one USB factory flash. Unchanged by this design.
- Fleet-wide cutover from `ota: platform: esphome` is out of scope until the
  canary has completed at least two weeks of orderly hourly cycles plus one
  successful pull update.
- Upstream contribution mechanics (PR against `JGAguado/Smart_Plant`, review
  cycle, doc updates in that repo). This document is our internal evaluation;
  upstream framing is a separate step.
