# SmartPlant naming architecture — locked target and migration contract

**Status: IMPLEMENTED IN REPOSITORY (rev 4); coordinated live cutover pending.**
Companion to `naming.md` (current-state field map). Owns the target model, its
rationale, and the contract for generating the AS-IS → future migration table. Feeds
Beads `infra-zdxz` (SmartPlant source/spec) and the Home Assistant handoff
`infra-kl21` (registry migration + dashboard side-effects). HA owns the
history-preservation mechanism.

The production facts below were rechecked read-only against all eight live YAML
files, ESPHome 2026.7.4, Home Assistant 2026.8.1, retained MQTT discovery, and
the HA registries. The
decisions are locked: preserve the effective runtime identities, put `mac6` in
every clean entity ID, migrate both `unique_id` and `entity_id` in place, and
preserve the e-paper arcs from a one-off HA threshold snapshot.

Keep the states distinct: the repository implements the target; Device Builder
has partially staged target literals and label assets; the eight active HA
entity sets still represent the historical deployed firmware. See `naming.md`
for the operational state map and Beads for current execution evidence.

---

## 1. Problem statement

In the **deployed firmware**, the entity layer has no independent name. Every one of the 10 exposed
entities is named `${friendly_name} <function>` in the packages, so the entities
inherit whatever `friendly_name` held at *first discovery*. Home Assistant
freezes an `entity_id` from the advertised name on first discovery and does not
update it on later discovery renames — so a past, overloaded `friendly_name` is
baked into every `entity_id`, automation, and dashboard reference until an
explicit HA registry rename. The observed result:

```
sensor.cuisine_guirlande_de_coeurs_cuisine_ceropegia_woodii_air_humidity
```

Decomposed, four independent naming sources had been concatenated into one
`friendly_name` and then frozen:

| Fragment | Source (historical) | Should have been |
|---|---|---|
| `cuisine_` | HA area (room) | not in the id |
| `guirlande_de_coeurs_cuisine_` | human / FR display | device display only |
| `ceropegia_woodii_` | botanical / technical slug | technical identity only |
| `air_humidity` | sensor function | **the only useful token** |

`cuisine` appears twice; the plant name appears in French *and* Latin. This is
structural coupling: the entity name is not owned by the entity, it is borrowed
from a display-ish field.

### 1.1 The two-Ceropegia stress case

Two devices are the same species (`Ceropegia woodii`) with the same French
community name (*Guirlande de cœurs*). The only natural discriminator is
technical: the MAC suffix (`54a8f2` / `54a99c`), already the project standard
(decision D1 — do **not** introduce room/index discriminators into identity).
Any model that puts the human or botanical name into the identity or the
`entity_id` re-creates a collision on these two. They are the correctness test
for the whole model.

### 1.2 Thresholds baked into the label image

The originally deployed e-paper "normal" page used a per-device PNG
(`page_1_background`, `platform: file`) with both the plant name and stale
recommended-range arcs baked into it. Repository target assets now contain only
the recovered illustration and HA-derived arcs, and regenerate byte-for-byte;
the name is rendered dynamically. Those assets are staged on the NAS but become
deployed truth only after the matching firmware is flashed.

---

## 2. What ESPHome actually does (RTFM, source-verified)

Verified against ESPHome tag **2026.7.4**:
`esphome/components/mqtt/mqtt_component.cpp` (discovery id formulas) and
`esphome/core/config.py` (`make_app_name_cpp`, MAC-suffix handling). The fleet
sets `discovery_unique_id_generator: mac` and leaves `discovery_object_id_generator`
at its default (`none`).

**unique_id (`mac` generator):**
```cpp
root[MQTT_UNIQUE_ID] = get_mac_address() + "-" + component_type() + "-" + fnv1_hash(friendly_name());
```
→ `<full-mac>-<component>-<fnv1(entity_name)>`. It hashes the **entity name**.
Renaming an entity changes the hash → changes the `unique_id` → HA sees a *new*
entity. Unavoidable when we change entity names (§3); it is the entire reason a
coordinated HA registry migration exists.

**object_id (`device_name` generator, OFF in deployed firmware):**
```cpp
StringRef object_id = this->get_default_object_id_to_(object_id_buf);
buf_append_printf(object_id_full, sizeof(object_id_full), 0, "%s_%s",
                  App.get_name().c_str(), object_id.c_str());
root[MQTT_OBJECT_ID] = object_id_full;
```
The default entity `object_id` is already the snake-cased, sanitised entity
name (`EntityBase::get_object_id_to`).
`App.get_name()` is the **runtime node name**: `configured_name` plus the MAC
suffix when `name_add_mac_suffix: true`, or `configured_name` verbatim when it is
`false`. Turning this generator ON makes HA derive the `entity_id` from a
*unique, MAC-bearing* node name instead of from the entity's display name.
`friendly_name()` in both formulas is the entity's own `name:`.

### 2.1 Deployed device display and MAC suffixing (load-bearing)

The firmware currently deployed on each device was compiled with an explicit
`esphome.friendly_name` human label. This is independent of:

- `substitutions.display_name`, used inside `device_comment`; and
- `substitutions.friendly_name`, the botanical/historical prefix used by entity
  names and special e-paper pages.

The deployed human label is therefore duplicated; `display_name` does not feed
the other two fields automatically in that firmware. The staged/target model
removes that duplication.

`make_app_name_cpp` (config.py) appends the 6-hex MAC suffix, at runtime, to
**both**:
- `name` — separator `"-"` → `cyperus-papyrus-54a9b2`
- `friendly_name` — separator `" "` (space) → `Papyrus 54a9b2`

…each only when the value is non-empty and `name_add_mac_suffix: true`.
**Consequence:** setting `esphome.friendly_name: ${display_name}` while keeping
`name_add_mac_suffix: true` would leak the MAC into the human HA device name
(`Papyrus 54a9b2`). This forces the identity decision in §3.

### 2.2 Why the clash is resolved (G1, resolved)

With `discovery_object_id_generator: device_name` **and** function-only entity
names, the object_id becomes `<node_name>_<function>`. `node_name` is unique
across all eight devices (it carries the MAC). The two Ceropegias therefore
produce **distinct** object_ids and distinct entity_ids — no `_2` auto-suffix,
no collision. Proven from source, not assumed.

---

## 3. Proposed target model

Three layers, **one source per layer**, no field doing two jobs.

| Layer | Single source | Drives | Changes on a human rename? |
|---|---|---|---|
| **Technical identity** | `configured_name` = `<device_name>-<mac6>`, `name_add_mac_suffix: false` | node name, hostname, MQTT topic prefix, discovery `object_id` prefix | No — immutable |
| **Device display** | `display_name` (`plants.yaml`, FR/community, strict typography) | `esphome.friendly_name` (HA device name), `device_comment`, e-paper text | Yes |
| **Entity** | function-only literal name | entity `name`; with MAC + component type, its MQTT `unique_id`; with node name, its discovery `object_id` and clean `entity_id` | Never — the function is fixed |

### 3.1 Uniform explicit identity on all 8 (forced by §2.1)

Because `name_add_mac_suffix: true` would push the MAC into `friendly_name`
(§2.1), the only coherent way to get a **clean human name** *and* keep **mac6 in
every entity_id** is to make the identity explicit on **all eight** devices, not
just the two Ceropegias:

```yaml
configured_name: "<device_name>-<mac6>"   # e.g. cyperus-papyrus-54a9b2
name_add_mac_suffix: false
esphome.friendly_name: "${display_name}"  # "Papyrus" — no MAC, because suffix is false
```

**This is identity-preserving, not an identity migration.** With
`name_add_mac_suffix: true` today the runtime node name already *is*
`<device_name>-<mac6>` (the value stored as `mqtt_topic_prefix` in
`plants.yaml`). Setting `configured_name` to that exact string with
`suffix: false` freezes the already-effective name: **hostname, MQTT topic
prefix, and retained topics are unchanged**; no OTA/retained migration. Only the
application-friendly-name suffixing changes. The two-Ceropegia special case in
the current package comment collapses — all eight then follow the same explicit
rule.

### 3.2 Firmware changes (implemented in repository; live cutover pending)

1. All 8 devices: `configured_name: "<device_name>-<mac6>"` +
   `name_add_mac_suffix: false` (identity-preserving, §3.1).
2. Replace each current literal `esphome.friendly_name` with
   `esphome.friendly_name: ${display_name}`, making `display_name` the single
   human source; retire the catch-all `${friendly_name}` entity prefix.
3. Rename the 10 exposed entities to **function-only** literals (e.g.
   `name: "Air Humidity"` instead of `name: "${friendly_name} Air Humidity"`).
4. Add `mqtt: discovery_object_id_generator: device_name`.
5. Keep `discovery_unique_id_generator: mac` (unchanged).

**REFUTED (canary 54a99c, HA 2026.8.1, 2026-09-03, infra-774o).** The firmware
does publish `obj_id = <node name>_<function>` with
`discovery_object_id_generator: device_name` (source: `mqtt_component.cpp`
@2026.7.4 and @dev emit `root[MQTT_OBJECT_ID] = object_id_full`). **But current
Home Assistant no longer derives `entity_id` from the discovery `object_id`.**
HA deprecated `object_id` → `entity_id` and stopped honouring it in HA Core
**2026.4**; the deployed broker's HA is **2026.8.1**. HA now derives `entity_id`
from `has_entity_name` (device/area name slug + entity name), so a payload's
`obj_id` is inert. The only discovery field that controls `entity_id` on current
HA is `default_entity_id` (payload abbreviation **`def_ent_id`**, e.g.
`"sensor.ceropegia_woodii_54a99c_air_humidity"`), honoured on first creation only.

**Firmware cannot emit `default_entity_id`.** ESPHome emits only the deprecated
`object_id` and has no config to emit `default_entity_id`/`def_ent_id`
(`esphome/esphome#12353` OPEN since 2025-12-08; `mqtt_component.cpp` @2026.7.4
**and** @dev verified — no such key; zero referencing/open/merged PRs). So **no
ESPHome version, and no ESPHome upgrade, unblocks this today.** A patched custom
component is the only firmware route and is rejected on cost (config-only fleet).

**Consequence — the "clean entity_id with zero HA action" goal is dead.** Canary
54a99c proved it directly: the 12 *fresh* rows (obj_id present, brand-new
`unique_id`, no pre-existing registry row) were created by HA as
`sensor.sejour_guirlande_de_coeurs_sejour_*` — **0/12** carry `ceropegia_woodii_54a99c`.
Row presence is irrelevant: `obj_id` is ignored either way, so the earlier
"fresh = clean-but-shadowed" model and the Path Y "delete + rediscover → clean"
idea are both void. A clean mac-bearing `entity_id` is achievable **only** by an
HA-side registry rename.

Two real per-device facts survive, both now handled entirely in HA (§4 / kl21):

- **Stale retained orphans.** Each device carries pre-cutover retained discovery
  payloads (different topic, never republished by new firmware → they do not
  self-clear). They must be emptied (`mosquitto_pub -r -n`) so HA removes the
  orphan rows. This is cleanup, not a route to clean ids.
- **Already-target-flashed device (Oxalis).** HA matches new discovery to
  pre-existing rows by `unique_id` and keeps their frozen `entity_id`s. Same
  outcome as the general case: an HA rename is required.

Net: **the fleet path is PATH HA** — per device, empty the stale retained topics
and rename the 12 fresh entities to the §3.3 target via WS
`config/entity_registry/update` (`new_entity_id`). Since Recorder history is
dropped by decision (no statistics/`unique_id` migration), this is a **purely
cosmetic rename**, deterministic and scriptable — no per-device judgment. Item 4
of the list above (`discovery_object_id_generator: device_name`) is retained for
`object_id` hygiene but is **inert for `entity_id`** on HA ≥ 2026.4.

The `device_name` slug (`cyperus-papyrus`, …) is an **opaque, immutable
identifier key**. Its resemblance to a taxon carries **no semantic authority**
(it is non-unique across the two Ceropegias) — it is not "the botanical name",
it is a historical key. We do **not** re-migrate it to `smartplant-<mac6>`: that
would be a second identity migration (hostname/MQTT/retained/OTA) for zero
operational gain (decision D-node).

### 3.3 Concrete entity_id result

```
AS-IS  (HA-frozen, per registry export): sensor.<historical-ugly-slug>_air_humidity
TARGET (HA-side rename, not firmware):   sensor.cyperus_papyrus_54a9b2_air_humidity
```

The TARGET is the deterministic string SmartPlant supplies as the rename goal; it
is **not** produced by firmware discovery (§3.2 — HA ignores the payload
`obj_id`). It exists only after the HA-side `new_entity_id` rename in §4. The mac6
is present in **every** entity_id — uniform across the fleet, language-neutral,
stable, honouring D1 (decision **D-mac**, now *forced* by the uniform-identity
model rather than an open choice). The AS-IS form varies per device and is **not
derivable from the current YAML** — it was frozen from a past `friendly_name` and
must be read from the HA registry (§4).

---

## 4. Home Assistant migration contract (for `infra-kl21`)

> **SUPERSEDED IN PART (decision 2026-09-03, drop-history).** Recorder history and
> statistics are disposable for this fleet, so the history-preservation machinery
> below — coupled `unique_id` + `entity_id` migration via `async_update_entity`,
> `migrate_discovery`, and statistics-metadata migration — is **no longer
> required**. Combined with §3.2 (HA ignores the payload `obj_id`; firmware cannot
> emit `default_entity_id`, `esphome#12353`), the fleet path reduces to a
> **cosmetic HA-side rename**: per device, empty the stale retained topics and set
> `new_entity_id` on the 12 fresh rows (delete the stale orphan rows). The detailed
> history-preserving contract below is retained for reference only; the live §4
> rewrite is owned by `infra-kl21`, not this SmartPlant doc. See `infra-774o`.

Changing the 10 entity names changes all their `unique_id`s per device → **80
new entities** fleet-wide at next discovery, orphaning the ~80 historical ones.
Without the coordinated mechanism below, dashboard, Recorder, and Plant-
integration references would also be stranded.

**SmartPlant delivers** (so HA needs no hash arithmetic and no SmartPlant-side
guesswork about frozen ids):

1. The **deterministic FUTURE mapping**, keyed by `(device, component_type,
   function)` → discovery topic, payload `obj_id`, target clean `entity_id`, and
   `unique_id`.
2. An explicit **"all 80 unique_id values change"** signal.

ESPHome 2026.7.4 keeps three similarly named values deliberately distinct:

```text
new_discovery_topic = homeassistant/<component>/<node>/<function_snake>/config
payload obj_id       = <node-dashed>_<function_snake>
new_entity_id        = <domain>.<node_underscored>_<function_snake>
```

`discovery_object_id_generator: device_name` prefixes the payload `obj_id`; it
does **not** change the final segment of the discovery topic. The tracked
generator has an exact regression fixture from the retained Oxalis bench
payload to prevent those fields being conflated again. The new `unique_id`
remains `<full-mac>-<component>-<fnv1(function-name)>`.

**HA/kl21 provides the other half and implements the fixed mechanism:**

- The **AS-IS side** (old frozen `entity_id` + old `unique_id`) comes from an **HA
  registry export** — it is not in SmartPlant's YAML. The full 96-row
  correspondence table is therefore a **joint artifact**: SmartPlant's FUTURE
  mapping joined to HA's AS-IS export.
- Preserving recorder history/statistics **and** getting clean entity IDs are
  **not** mutually exclusive: HA's runtime registry API (`async_update_entity`)
  changes `new_unique_id` and `new_entity_id` together, and Recorder migrates
  states metadata plus statistics metadata on the entity-ID rename.
- `migrate_discovery` and `async_update_entity` are complementary, not
  alternatives. Per device: publish `migrate_discovery: true` on the 12 old
  discovery topics; confirm the entities unload while their registry rows
  remain; update each row's `unique_id` and `entity_id` through HA's runtime
  registry API; flash the matching firmware; verify the 12 new discovery
  payloads reattach to those same rows; then clear the exact old retained
  discovery topics.
- **Do not hand-edit the live `.storage/core.entity_registry`** (kl21's own
  rule). Take HA and exact registry backups first; use the runtime API,
  canary-first. An offline remap is rollback-only contingency, not the normal
  path.

The distinction that must be explicit in the handoff: a UI rename only covers
`entity_id` (history follows); `unique_id` preservation is not a UI action, so
the effort must not be under-scoped as "a simple rename".

### 4.1 Required mapping and rollback

The generated mapping has exactly one row per active entity and these minimum
columns:

```text
inventory_key, device_id, component_type, function,
old_discovery_topic, old_entity_id, old_unique_id,
new_discovery_topic, new_object_id, new_entity_id, new_unique_id
```

Validation rejects anything other than 80 unique source rows and 80 unique
targets. The preflight also captures every old retained discovery payload, all
entity-ID consumers, each live YAML checksum, `name_by_user`, an HA backup ID,
and an exact `core.entity_registry` backup checksum. These are rollback inputs,
not permission to edit `.storage` live.

If a canary fails after migration has started, stop the fleet. Put the new
discovery topics into migration mode, unload the new entities, restore each old
`unique_id` and `entity_id` through the HA runtime registry API, restore the old
live YAML and validated firmware, republish the captured old discovery payloads,
restore `name_by_user` and all changed references, then verify the original 12
rows and Recorder continuity. Restore the full HA backup only if this targeted
rollback cannot re-establish the captured state.

### 4.2 Amended path for an already-target-flashed device (Oxalis)

The §4 sequence assumes a clean pre-cutover device: one coupled AS-IS set, with the
12 target `unique_id`s free. Oxalis breaks that assumption — it was flashed to the
target firmware during the `infra-zdxz.3` bench, so `core.entity_registry` holds 24
enabled mqtt rows on the one device (`device_id
c4e0f66680eff0befd322fc390a576bc`, verified read-only 2026-09-03):

- **history-bearing coupled set** — `unique_id 4827e25326ba-*-53accb91…`, entity_id
  `sensor.sejour_oxalis_triangularis_oxalis_triangularis_*`. ~6.5 months of recorder
  history since 2026-02-14 (kl21.5: 4814 long-term rows on Air Humidity), frozen
  when the target firmware took over on 2026-09-02;
- **target set** — `unique_id 4827e25326ba-*-da2b7bfa…` (the exact `new_unique_id`s
  from the 96-row map), entity_id `sensor.sejour_trefle_pourpre_*`. A pre-2026-02
  orphan revived by the bench flash — live but on the wrong entity_id, ~17 long-term
  rows only.

Both sets are separate from the HA Plant/template layer (`plant.trefle_pourpre`,
`device_id e961e5…`, `platform: plant`, own `unique_id` scheme, since 2024-10-22),
which is out of scope for this migration.

Because the 12 target `unique_id`s are already present, the plain §4 in-place
`unique_id` swap on the coupled set cannot be applied directly — HA rejects a
duplicate `unique_id` within the mqtt platform. §3.2's clean-entity_id assumption
also failed here (see §3.2 caveat): HA kept the frozen `sejour_trefle_pourpre_*`
entity_ids.

**The reconciliation mechanism is owned by HA/kl21, not specified here.** SmartPlant
delivers only the validated end-state constraints kl21 must satisfy for Oxalis:

- the 6.5-month recorder history currently keyed to the coupled entity_ids
  (`sensor.sejour_oxalis_triangularis_*`, uid `…-53accb91…`) must be preserved on
  the target entity_ids (`sensor.oxalis_triangularis_5326ba_*`, uid `…-da2b7bfa…`);
- the 12 target `unique_id`s are already occupied by the revived-orphan set
  (`sensor.sejour_trefle_pourpre_*`), so they must be freed/reassigned before or as
  part of binding them to the history-bearing rows — whatever HA-side path kl21
  chooses (registry reassignment, discovery migration, recorder metadata) is theirs;
- the ~17 bench statistics on the revived-orphan set are disposable (redundant with
  the coupled set and the plant layer);
- watch the retained-discovery reattach ordering: the firmware's retained target
  discovery (`…-da2b7bfa…`) is still in the broker, so a naive registry edit can be
  undone by HA re-processing that retained payload. Sequencing is kl21's.

The firmware-flash step of §4 is a no-op for Oxalis (already flashed). The other
seven devices are unaffected and follow §4 as written (0/12 target `unique_id`s
present in the registry).

---

## 5. Label-maker and thresholds (D-lm — resolved)

Label-maker per-plant JSON carries three things; the PNG bakes them into the
normal e-paper page:

| JSON field | Meaning | Target home |
|---|---|---|
| `title.value` | common / FR name | ← `display_name` |
| `subtitle.value` | botanical/cultivar description | ← generated `secondary_name` (`botanical_name`, then `horticultural_name`) |
| `parameters.*.rel_range` | recommended-range **arcs** (moisture/light/temp/humidity) | ← thresholds, **HA-authoritative** |

**The name half is implemented:** the normal page renders `display_name` +
`secondary_name`
as **dynamic text** (same path as the maintenance/storage pages), so a rename
needs no image work. The versioned PNG becomes name-free and contains only the
illustration plus threshold arcs derived from the one-off HA snapshot. This part
is owned by `infra-zdxz.3`; repository and Oxalis bench evidence exist, while the
final coordinated fleet flash remains pending.

The arcs remain because they are useful visual guidance on an offline e-paper
display. They do **not** need a runtime MQTT threshold subscription: these are
stable plant-care values, not operational control inputs.

During the coordinated migration, the implementation reads the current values
from the HA-authoritative plant configuration once and records a reproducible
snapshot containing, for each plant and metric:

- the HA source entity/config entry and exact min/max values with units;
- extraction timestamp and running HA version;
- the deterministic conversion into the arc-rendering inputs.

The generated firmware/art inputs are derived snapshot data, not a second
independently maintained horticultural policy. `plants.yaml` may reference the
versioned snapshot or generated artifact but must not duplicate those values for
manual editing. There is no automatic resynchronisation. If someone later
changes HA thresholds, refreshing the e-paper snapshot is an explicit one-off
maintenance operation; the accepted premise is that such changes are rare.

---

## 6. AS-IS → future mapping contract

### 6.1 Name fields

| # | Field | AS-IS role | Future role |
|---|---|---|---|
| 1 | `substitutions.device_name` | opaque identity key | unchanged — opaque immutable key |
| 2 | `substitutions.configured_name` | `=device_name` (6) / explicit `<name>-<mac6>` (2 Cero) | **explicit `<name>-<mac6>` on all 8** |
| 3 | `substitutions.name_add_mac_suffix` | `true` (6) / `false` (2 Cero) | **`false` on all 8** (§3.1) |
| 4 | `substitutions.friendly_name` | every entity name + special e-paper text | **removed** — entities become function-only |
| 5 | `substitutions.display_name` | human literal used by `device_comment`; duplicated separately in `esphome.friendly_name` | the single human source → `esphome.friendly_name` + `device_comment` + e-paper |
| 6 | `esphome.friendly_name` | explicit human literal in all 8 deployed images; MAC appended on the 6 suffix-enabled devices | `${display_name}` (no MAC, suffix false) |
| 7 | `esphome.comment` (`device_comment`) | `${botanical/horticultural} / ${display_name}` in live devices; ESPHome metadata exposed by its web server when enabled, with no MQTT/native-API HA path assumed | `${secondary_name} / ${display_name}` |
| 8 | entity `name:` | `${friendly_name} <function>` | `<function>` (function-only) |
| 9 | `page_1_background` PNG | name + stale thresholds + art baked | name-free art + arcs generated from the versioned one-off HA snapshot |
| 10 | `name_by_user` (HA) | populated on all 8 MQTT devices, masking the raw firmware name | empty on all 8 after canary validation |

### 6.2 The 10 exposed entities (per device)

`node = <configured_name>` (e.g. `cyperus-papyrus-54a9b2`). Future `entity_id` =
`<domain>.<node_sanitized>_<function>`, for example
`sensor.cyperus_papyrus_54a9b2_air_humidity`. AS-IS `entity_id` is the HA-frozen ugly form
(**from registry export**, varies per device); every `unique_id` changes because
the name changes.

| Component (ESPHome) | HA domain | AS-IS name | Future name | Future entity_id (papyrus) |
|---|---|---|---|---|
| sensor (max17043) | sensor | `${fn} Battery` | `Battery` | `sensor.cyperus_papyrus_54a9b2_battery` |
| sensor (aht10 temp) | sensor | `${fn} Temperature` | `Temperature` | `sensor.…_temperature` |
| sensor (aht10 hum) | sensor | `${fn} Air Humidity` | `Air Humidity` | `sensor.…_air_humidity` |
| sensor (veml7700) | sensor | `${fn} Ambient light` | `Ambient light` | `sensor.…_ambient_light` |
| sensor (adc soil) | sensor | `${fn} Soil Moisture` | `Soil Moisture` | `sensor.…_soil_moisture` |
| text_sensor (version) | sensor | `${fn} ESPHome Version` | `ESPHome Version` | `sensor.…_esphome_version` |
| switch (maintenance) | switch | `${fn} Maintenance` | `Maintenance` | `switch.…_maintenance` |
| switch (storage) | switch | `${fn} Storage Mode` | `Storage Mode` | `switch.…_storage_mode` |
| text_sensor (maint status) | sensor | `${fn} Maintenance Status` | `Maintenance Status` | `sensor.…_maintenance_status` |
| text_sensor (storage status) | sensor | `${fn} Storage Mode Status` | `Storage Mode Status` | `sensor.…_storage_mode_status` |

`${fn}` = `${friendly_name}` (the coupled catch-all being removed). This table is
exactly the 12 MQTT-discovered registry entities per production device: 8 × 12 =
96 rows. `Battery voltage` and `Actual gain` are `internal: true` and excluded
from the HA migration. The complete correspondence artifact is generated, not
hand-authored: it joins the HA export (`old_entity_id`, `old_unique_id`) with the
deterministic target (`new_entity_id`, `new_unique_id`) for all 96 rows.

---

## 7. Resolved decisions and implementation gates

| ID | Item | Status |
|---|---|---|
| G1 | entity_id uniqueness for the 2 Ceropegias under `device_name` generator | **Resolved** — source-proven (§2.2) |
| G3 | e-paper font glyph coverage and layout | **Resolved in source/bench** — Audiowide + `GF_Latin_Core`; 20/15 sizes retained; operator accepts battery/time overlap for long names; final canary render remains a deployment gate |
| D-mac | mac6 in every entity_id (uniform) | **Forced** by the uniform-identity model (§3.1), no longer an open choice |
| D-node | preserve hostname/MQTT slugs as opaque historical keys | **Resolved** — no re-migration (§3.2) |
| D-hist | preserve recorder history vs recreate clean | **Both achievable together** via HA runtime API; kl21 owns the mechanism (§4) |
| D-lm | e-paper threshold arcs | **Resolved** — preserve them from a versioned one-off HA-derived snapshot; no runtime sync (§5) |

Dropped from rev 1: **G2** (`str_sanitize`/`str_snake_case` mangling
`œ`/accents in the id) — moot, because sanitisation applies to the **entity**
name (function-only, ASCII), never to `display_name`. Unicode in the human name
only reaches `esphome.friendly_name` (HA handles it) and the e-paper (that is
G3).

## 8. Implementation and cutover sequence

1. `infra-zdxz.1` **complete**: keep `naming.md` accurate for current production
   and this document as the locked target/runbook contract.
2. `infra-zdxz.2` **implemented in repository**: firmware refactor — uniform explicit identity (all 8,
   identity-preserving), function-only entity names, `display_name`,
   object_id generator — + regression tests (identity stable under display
   rename; hostname/MQTT prefix byte-identical before/after).
3. `infra-zdxz.3` **implemented in repository and bench-validated on Oxalis**:
   extract the one-off HA threshold snapshot, generate name-free
   e-paper art/arcs, render names dynamically, and declare `GF_Latin_Core`.
4. `infra-kl21.1/.3/.4` **complete**: capture the AS-IS registry/threshold inputs
   and generate the 96-row correspondence table.
5. `infra-kl21.2` **pending**: perform the
   coordinated `migrate_discovery` → runtime registry update → firmware cutover,
   canary first, including dashboard/Plant/recorder references.

Repository implementation is not deployment evidence. The remaining cutover
requires the owning Beads issues, their rollback prerequisites, and Florent's
explicit authorization for each live write, cache reset, compile, upload, or
flash.
