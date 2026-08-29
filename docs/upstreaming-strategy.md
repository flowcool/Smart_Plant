# Upstreaming strategy — flowcool/Smart_Plant → JGAguado/Smart_Plant

Owning issue: **infra-3rr.26**. Related: infra-3rr.21 (API/MQTT profile coordination,
upstream issue #24), infra-3rr.25 (low-battery hibernation), infra-3rr.23 (pull-OTA).

Baseline of this analysis:
- Fork `flowcool/Smart_Plant@V2R1` at `c165d67`.
- Upstream integration branch is **`upstream/V2R1`** (105 commits ahead of `upstream/main`),
  NOT `main`. All merged PRs (#9,#12,#13,#17,#18,#19,#20,#22, and #25) landed on `upstream/V2R1`.
- merge-base(V2R1, upstream/V2R1) = `890251b`. We are **58 commits ahead / 2 behind**.

## 1. Divergence map (evidence)

The 74-file / 277k-insertion raw diff vs `upstream/main` is dominated by binaries
(Enclosure STL, doc images). The firmware-significant delta vs `upstream/V2R1` is 5 files:

| File | Δ lines | Exists upstream? | Nature |
|---|---|---|---|
| `docs/source/files/configuration.yaml` | 41 | yes (newcomer single-device file) | **Shared surface — upstream-worthy** |
| `examples/multi-device/packages/smart_plant_base.yaml` | 799 (on top of upstream's 344) | **yes (344-line version)** | Fork package (mixed: some features upstream-worthy, some MQTT-bound) |
| `examples/multi-device/plants.yaml` | 139 | no | Fleet identity registry — fork-only |
| `scripts/esphome_fleet_update.py` | 495 | no | Fleet tooling — fork-only |
| `examples/multi-device/my-lemon-tree.yaml` | 21 | **yes** | Device overlay example |

**Key structural fact — corrected 2026-08-29:** the multi-device folder is **already merged
upstream**. `examples/multi-device/` (device overlay + `packages/smart_plant_base.yaml` with an
`mqtt:` block, 344 lines) exists on `upstream/V2R1` — merged via an earlier PR. It carries the
MQTT data-path + deep_sleep foundation but **not** maintenance / storage / pull-OTA / low-batt
(0 hits upstream). Our package is that same file plus **799 lines of advanced features on top**
(1098 lines total). So the divergence is additive *within an already-shared file*, not a
net-new fork file.

The two-profile model agreed in issue #24 (**simple native-API** `configuration.yaml` vs
**advanced MQTT** `smart_plant_base.yaml`) is therefore **already the upstream layout** — one
branch, both profiles side by side. See §8 (folder vs branch).

**Documentation gap:** the multi-device/MQTT profile is present in upstream's tree but **absent
from its narrative docs**. `docs/source/programming.rst` still teaches only the single-device
`configuration.yaml` (it still describes the old `consider_deep_sleep` 95% script); `README.md`
has zero mention of multi-device/MQTT/packages. The advanced profile is invisible to a reader.

Feature presence, package vs newcomer config (V2R1):

| Feature | package | config-base |
|---|---|---|
| low-batt / hibernation | present | absent |
| pull-OTA (`http_request`/`update:`) | present | absent |
| maintenance | present | absent |
| storage | present | absent |
| lifecycle (safe_mode + bounded deep_sleep) | present | present (the 41-line fix) |

## 2. Two-direction gap

- **We lack from upstream (2 commits):** PR #25 `fix: migrate image: block to platform syntax`
  (`b5d9ba4`/`15b7bde`), the ESPHome 2027.1.0 image syntax. We already made the same fix
  independently (our `configuration.yaml` and package both use `platform: file`), so it is
  convergent — a rebase resolves it trivially. **Note:** `CLAUDE.md` says "PR #23 … open" for
  this; reality is **#25, merged on `upstream/V2R1`**. That project-doc line is stale.
- **We are ahead (58 commits):** almost entirely the fork package + tooling + docs/beads noise.

## 3. Coupling audit (gate 1) — feature × MQTT × portability

Full read of `smart_plant_base.yaml@V2R1`. Verdicts are evidence-based, not asserted.

| Feature | MQTT-coupled? | Portable to native `configuration.yaml`? | Upstream form | Effort |
|---|---|---|---|---|
| Lifecycle: `safe_mode.mark_successful` + bounded deep sleep | No | Already done (41-line delta) | active | — |
| **E-paper BUSY-settle** (`settle_display`, `recover_display_busy`, `sleep_after_display`) | No ¹ | **Yes** | active | M |
| **I2C rail settle 250 ms** before MAX17043 wake (on_boot priority 700) | No | **Yes** | active | S |
| **Low-batt hibernation + WARN invert** (NVS latch, `page_low_batt`, hibernation branch) | **No ²** | **Yes** | active | M |
| **Pull-OTA** (`http_request` + `update:` + `pull_ota_enabled`) | No for the primitives ³ | **Yes, but** trigger must be reformulated | **commented / opt-in + doc** | M–L |
| Maintenance mode (retained `/cmd/maintenance`, watchdog, `ota_min_battery`) | **Yes, by nature** | No | fork / advanced profile | — |
| Storage mode (retained `/cmd/storage_mode`, 24 h sleep) | **Yes, by nature** | No | fork / advanced profile | — |
| Data path: MQTT + API-metadata-only | Architectural | No | fork | — |

**¹** `settle_display`/`recover_display_busy` are pure `digitalRead(GPIO)` + globals. Only
coupling = one `maintenance_status "DISPLAY_BUSY_TIMEOUT"` publish (base l.713), replaceable by
`logger.log` in the native profile. Universal value: the legacy Waveshare driver
(ESPHome 2026.7.4) returns after MASTER ACTIVATION but before BUSY clears — every owner of this
panel hits it.

**²** Verified line-by-line: `low_batt_active` (NVS global), evaluated in
`render_measurement_page` (pure lambda on `batpercent`), `page_low_batt` (pure display),
hibernation = `deep_sleep.enter` with a longer duration. **Zero `mqtt.publish` in the entire
low-batt path.** Only adherence: `page_low_batt` reads `storage_active` for one optional
secondary line (base l.639) — trivially removable. Confirms "adds value for everyone".

**³** Primitives (`http_request`, `update: platform: http_request`, template switch) are
MQTT-free. What is coupled: (a) the **trigger** `update.check` buried in `decide_sleep`
(maintenance window = MQTT state machine), (b) two status `mqtt.publish` (base l.283-287,
strippable). So the primitives port; the trigger needs a native-appropriate reformulation.

## 4. Remaining gates before any PR (do not pre-decide)

1. **Low-batt** must be **fleet-validated first** (infra-3rr.25.9, HUMAN GATE, open) before an
   upstream PR. Upstreaming an unproven feature is premature.
2. **Pull-OTA native trigger** is a **design question** (HA-side `update` entity press? a button?
   on_boot check?) and touches the API/MQTT boundary → **coordinate on issue #24** (infra-3rr.21,
   awaiting JGAguado). Blocked by #24.
3. **E-paper settle** targets the legacy driver at ESPHome 2026.7.4 + model `2.90inv2`. Upstream
   uses the same model → likely applies unchanged, but **verify against upstream's driver version**
   before asserting.

## 5. Upstream sequence (value/risk order)

0. **Document the advanced multi-device/MQTT profile** (`programming.rst` + `README.md`) →
   **zero firmware risk, highest leverage.** The profile is already merged upstream but invisible
   in the docs (see §1 documentation gap). This is a pure-docs PR keeping single-device as the
   documented default and signposting the advanced folder. Do first — unblocks nothing but costs
   nothing and independent of #24.
1. **I2C settle 250 ms** + **E-paper BUSY-settle** → active PRs, independent of #24, not blocked.
   Highest firmware value/risk ratio. Target `upstream/V2R1`; rebase over #25 first to drop the
   convergent image-syntax delta.
2. **Low-batt hibernation + WARN invert** → active PR **after** the fleet gate (25.9).
3. **Pull-OTA** → commented/opt-in block in `configuration.yaml` + doc note, **after** trigger
   design + #24 agreement.
4. **Maintenance / Storage** advanced features (retained control) → layer onto upstream's existing
   344-line package under `examples/multi-device/`, documented as the advanced profile. Not into
   the newcomer `configuration.yaml`.

## 6. What stays a deliberate fork

`plants.yaml` fleet registry, `esphome_fleet_update.py` fleet tooling, botanical naming
migration (infra-b5q). These are fleet-operations product specific to our deployment and are not
upstream-worthy. Note: the MQTT package and maintenance/storage control are **advanced-profile**,
not fork-only — they belong in upstream's existing `examples/multi-device/` folder (§8), just not
in the newcomer `configuration.yaml`.

## 7. No-urgency note

`upstream/V2R1` is effectively frozen relative to us (2 convergent commits). The "fork becomes
unmergeable" risk is low; there is no decay pressure. This work is P3 and should proceed
deliberately behind its gates, not as a rushed batch.

## 8. Folder vs branch for the advanced/MQTT profile (#24 coordination)

In issue #24 JGAguado proposed a **dedicated branch** for the MQTT/advanced work to protect
newcomer simplicity. Recommendation: **keep a single-branch folder model instead** — and note it
is *already the upstream reality*.

Evidence:
- `examples/multi-device/` (device overlay + `packages/smart_plant_base.yaml` with `mqtt:`) is
  **already merged on `upstream/V2R1`**, on the same branch as the simple `configuration.yaml`.
  The folder-holds-MQTT layout was already accepted in practice.
- Newcomer simplicity is achieved by **navigation, not branch isolation**: repo-root
  `configuration.yaml` stays the documented default; the advanced profile lives under
  `examples/multi-device/` and is reached only by readers who want it. This is standard ESPHome
  ecosystem layout (a `packages/` folder + thin device overlays).
- A separate branch would **institutionalise cross-branch drift** — every shared-core fix
  (sensors, e-paper settle, lifecycle) would need merging across two heads. That is exactly the
  divergence infra-3rr.21 warns against. A single branch keeps ONE shared core; the two profiles
  are thin overlays / an included package.
- Our fork is the empirical proof the folder+package model works at 8-device scale.

Coordination stance on #24: do not debate "which branch"; propose "keep the single-branch folder
we already have, and document both profiles" — lower maintenance for the maintainer, same
newcomer protection. The only real deliverable there is documentation (§5 item 0), not a branch.
