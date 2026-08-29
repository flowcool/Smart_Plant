# Transport decoupling plan (model B) — API vs MQTT ⊥ multi-device

Owning issue: **infra-3rr.34** (RTFM + plan). Feeds the deferred consolidated upstream PR
(infra-3rr.26 strategy). Implementation is a SEPARATE issue created only after this plan is agreed.

## 1. Problem

`examples/multi-device/packages/smart_plant_base.yaml` (1098 l.) welds two orthogonal axes:

- **Axis 1 — device count:** single vs fleet. Solved by the *package* system (shared logic +
  thin per-device overlays). Independent of transport.
- **Axis 2 — transport:** native API vs MQTT. What talks to Home Assistant.

MQTT is coupled to the package because of **deep sleep**, not device count:
1. **HA freshness** — under deep sleep the native API goes `unavailable` each cycle; retained
   MQTT values survive sleep.
2. **Remote control** — a sleeping device cannot receive a live API command; a retained MQTT
   command waits for its next wake (maintenance / storage).

So the real cleavage is **API (fine while powered/awake)** vs **MQTT (needed for good HA UX with
deep sleep + retained remote control)** — exactly the two-profile model of upstream issue #24. A
multi-device user on continuous power can run native API; a single deep-sleep device benefits
from MQTT as much as a fleet. Model B makes transport a **selectable overlay**, orthogonal to the
multi-device package factoring.

## 2. RTFM findings — ESPHome package merge (target ~2026.7.x)

Sources: official Packages doc and `esphome-docs/content/components/packages.md`.

- **F1 — Multiple packages per device:** standard and supported (`packages:` maps several named
  packages; keys are labels only).
- **F2 — List merge:** *component* lists (with an `id:`) merge **by id**; all other lists merge by
  **concatenation**. So `sensor:`/`switch:`/`script:` entries from several packages append.
- **F3 — Dict/scalar merge:** dicts merge key-by-key; scalars are replaced; **main config
  overrides packages**.
- **F4 — Nested packages:** supported (a package may carry its own `packages:`), **but
  historically buggy** — vars expansion (esphome#12269), include-depth validation (esphome#11301),
  include path resolution (esphome#14583). **Decision: avoid nesting; compose flat siblings.**
- **F5 — `!extend <id>` / `!remove <id>`:** modify or remove included config by id. Whether
  `!extend` **appends** to an action list (`then:`) or a `pages:` list is **undocumented** →
  the design must NOT depend on it (see G1).

## 3. Target architecture — flat sibling composition

Each device YAML composes two flat sibling packages (no nesting):

```yaml
packages:
  core:      github://flowcool/Smart_Plant/.../packages/core.yaml@V2R1
  transport: github://flowcool/Smart_Plant/.../packages/profile-mqtt.yaml@V2R1   # or profile-api.yaml
```

### 3.1 `core.yaml` — transport-agnostic

Holds everything with no transport dependency and **no `mqtt.publish`, no `mqtt:`/`api:`, no
`on_boot`**:

- substitutions (shared defaults), `esp32`, `i2c`, `spi`, `font`, `image`, `time`, sensors
  (MAX17043, AHT20, VEML7700, ADC soil), `deep_sleep`.
- **All display pages** (`page1`, `page_low_batt`, `page_storage`, `page_maintenance`). API mode
  simply never navigates to the storage/maintenance pages (negligible unused-flash cost; avoids
  the undocumented `!extend pages:` path — see G1).
- globals used by core: `low_batt_active` (NVS), `storage_active` (NVS, **declared in core,
  written only by profile-mqtt**, read by the core display), `display_settle_ok`,
  `display_busy_seen`, `display_safe_to_sleep`.
- transport-agnostic scripts: `hw_settle` (the 250 ms I2C-rail delay), `sample_battery`,
  `acquire_normal` (**refactored to NOT call `decide_sleep`** — see §4), `render_measurement_page`
  (low-batt evaluation + page select), `settle_display`, `recover_display_busy`,
  `sleep_after_display`, `enter_deep_sleep` (low-batt hibernation + storage-duration branch; both
  branches key off core globals; no MQTT).

### 3.2 `profile-mqtt.yaml` — advanced

- `mqtt:` block (+ the metadata-only `api:` as today), `http_request`/`update`/pull-OTA.
- `on_boot`: `hw_settle` → wait `mqtt.connected` → `prepare_cycle`.
- MQTT-only globals: `maintenance_requested/active`, `maintenance_end_*`, `storage_requested`,
  `storage_display_refresh_pending`, `preserve_maintenance_status`, `boot_sequence_complete`.
- switches (`maintenance_control`, `storage_control`, `pull_ota_enabled`), status text_sensors,
  and all maintenance/storage scripts (`prepare_cycle`, `decide_sleep`, `maintenance_watchdog`,
  `enter_storage`, `exit_storage`, `exit_maintenance`) + every `mqtt.publish`. `ota on_end`
  handler lives here.

### 3.3 `profile-api.yaml` — simple

- `api:` block (full, not metadata-only). No MQTT, no maintenance/storage.
- `on_boot`: `hw_settle` → `prepare_api` = `sample_battery` → `acquire_normal` →
  `render_measurement_page` → `sleep_after_display`. Deep-sleep + low-batt hibernation still work
  (core). Under deep sleep the API device is `unavailable` between wakes — a documented tradeoff,
  the reason MQTT exists.

## 4. Refactor delta from the current single package

Mechanical, bounded:

1. **Split file** into `core.yaml` + `profile-mqtt.yaml`; the current 8 devices switch to
   `core` + `profile-mqtt` (behaviour-preserving — same components, just recomposed).
2. **Move** `storage_active` global declaration into `core` (writer stays in profile-mqtt).
3. **Cut the `decide_sleep` tail out of `acquire_normal`.** Today `acquire_normal` ends with
   `script.execute: decide_sleep` (an MQTT-profile script). Core's `acquire_normal` must end
   without it; each profile's entry script chains the next step (profile-mqtt → `decide_sleep`;
   profile-api → `render_measurement_page` → `sleep_after_display`).
4. **Move** `on_boot` out of core entirely (each profile owns its own).
5. **Extract** the 250 ms I2C settle into a core `hw_settle` script both profiles call first.
6. **Create** `profile-api.yaml` fresh (new small file).

Nothing moves that carries `mqtt.publish` into core; nothing in core references an MQTT-only
global except `storage_active` (declared in core).

## 5. Numbered gates — proven by `esphome config`, NO device

`esphome config <scratch-device>.yaml` expands + schema-validates the merged result. All gates are
local/CI, hardware-free.

- **G1 — same-id merge / `!extend` avoidance:** confirm the chosen design never needs to append to
  a core component's sub-list from a profile (pages/actions). Prove the all-pages-in-core approach
  validates; if a future need arises, prove `!extend` append semantics before relying on them.
- **G2 — substitution precedence, sibling packages:** core defaults vs profile overrides vs device
  overrides. Docs give main>package, not sibling-vs-sibling. Prove the effective substitution set
  on a composed scratch device is what we expect.
- **G3 — core global written only by profile:** `storage_active` declared in core, set true only
  by profile-mqtt, read by core display. Prove profile-api composition validates/compiles with the
  writer absent (global stays false).
- **G4 — core is composition-only:** core alone is an incomplete device (no `on_boot`, no
  transport). Prove `core + profile-*` composes to a valid device; document that core is never
  flashed standalone.
- **G5 — two flat remote packages via `github://`:** we already use one remote package; prove two
  flat remote packages resolve together (we do not use `esphome: includes:`, so the path bug
  #14583 is expected N/A — confirm).

## 6. Phasing

1. **RTFM (this issue, done):** merge semantics established; flat-sibling architecture chosen.
2. **Gate-prove (scratch compose):** author throwaway `core.yaml`/`profile-*.yaml` skeletons +
   scratch device files; run `esphome config` to clear G1–G5. **No device.** Blocking before refactor.
3. **Refactor (separate issue):** split the real package per §3–§4; keep clean per-feature commits.
4. **Compose-validate both profiles:** `esphome config` on a real device file for each profile;
   diff the profile-mqtt expansion against today's single-package expansion to prove behaviour
   preservation.
5. **Migrate the 8 devices** to `core + profile-mqtt` (one canary first, per nas-operations;
   behaviour-preserving, OTA). Only after this is the fork stabilised.
6. **Feeds the consolidated upstream PR** (infra-3rr.26): upstream then receives core + both
   profiles, offering API *and* MQTT instead of imposing MQTT.

## 7. Rollback / blast radius

- Steps 1–4 change no device (paper + scratch validation only). Blast radius: none.
- Step 5 is a normal OTA migration: the package is pinned `@V2R1`; devices keep running the current
  image until re-flashed. Rollback = re-flash the pre-refactor package tag by OTA/USB, purge the
  NAS package cache. Canary + two wake/sleep cycles before the fleet (nas-operations).
- The refactor is behaviour-preserving for profile-mqtt; profile-api is net-new and touches no
  existing device until someone opts in.

## 8. Decisions (settled 2026-08-29)

- **Naming (explicit, no alias):** `smart_plant_core.yaml` + `smart_plant_profile_mqtt.yaml` +
  `smart_plant_profile_api.yaml` under `examples/multi-device/packages/`. The old
  `smart_plant_base.yaml` is retired; the 8 devices are repointed to `core + profile_mqtt` during
  migration (phase 5). Explicit filenames over a backward-compat alias.
- **profile-api built now:** a minimal `smart_plant_profile_api.yaml` is authored during
  gate-prove (phase 2) — it is the actual proof that transport is decoupled.
