# Naming model — how a plant's name flows through the stack

> **Scope:** this page maps the **current** (coupled) naming reality and the
> rename traps. The **target** model that decouples identity / display / entity
> naming — and its 96-row migration-table contract — is locked in
> [`naming-architecture.md`](naming-architecture.md) (Beads `infra-zdxz`). Until
> that migration lands, this page remains the authority for the live fleet.

This project has **several independent name fields**. They are easy to confuse:
changing one does not change the others, and `entity_id` never follows a rename
automatically after first discovery. This page is the map. Read it before you
rename anything.

## The name sources

| Field | Where it is set | What it drives | Follows renames? |
|---|---|---|---|
| `substitutions.device_name` | device YAML | ESPHome node name + (with `name_add_mac_suffix`) the **hostname** and **MQTT topic prefix** | — (identity; do not change casually) |
| `substitutions.display_name` | device YAML | human label; currently interpolated into `device_comment`. It is also duplicated as a literal in `esphome.friendly_name` | you must edit both current literals consistently |
| `substitutions.friendly_name` | device YAML | **every entity name** (`${friendly_name} Temperature`, …) **and** the subtitle text on the maintenance / storage / low-batt e-paper pages (`smart_plant_core.yaml`) | you must edit the YAML |
| `substitutions.device_comment` → `esphome.comment` | device YAML | ESPHome comment metadata, exposed by ESPHome's web server when enabled; no MQTT/native-API path to HA is assumed | you must edit the YAML |
| `esphome.name` (`= ${configured_name}`, +MAC when `name_add_mac_suffix: true`) | shared package + device substitutions | ESPHome node name, hostname and MQTT topic prefix | — (identity) |
| `esphome.friendly_name` (`esphome:` block) | each live device YAML | suggested MQTT device name in Home Assistant; ESPHome appends ` mac6` on the six devices still using `name_add_mac_suffix: true` | you must edit the YAML |
| `page_1_background` label image | per-device PNG on the NAS (`esphome/plant_labels/`) | the plant name shown on the **normal measurement page** (a rendered image, not text) | regenerate the PNG |
| `name_by_user` | Home Assistant device registry (UI rename, or `ha_set_device`) | the device name shown **in the HA UI**, overriding `esphome.friendly_name` | it *is* the rename — but see the trap below |
| `entity_id` | Home Assistant registry, initially derived at first discovery | the entity's stable reference (`sensor.<slug>_temperature`) | not automatically; only an explicit registry rename |

## The two traps

1. **`entity_id` is frozen against automatic discovery renames.** It is
   slugified from the name a device advertised the *first* time HA saw it. It
   follows **neither** `friendly_name` **nor** `name_by_user` afterwards.
   Renaming a device leaves the old slug in every `entity_id`, automation, and
   dashboard reference. To actually change an `entity_id` you must update it in
   HA's registry (or delete + rediscover) — deliberately, once.

2. **`name_by_user` is a hidden override.** Renaming a device in the HA UI writes
   `name_by_user`, which *masks* the `esphome.friendly_name` the firmware sends.
   The firmware value is still there, just invisible — until someone clears
   `name_by_user` (a device "reset name"), at which point the UI silently reverts
   to the firmware value. Two sources of truth that only agree by luck.

## The target rule: one point of edit

Hand-edit the display name only in `examples/multi-device/plants.yaml`; consume
it through generated **YAML**, and leave `name_by_user` **empty after the
coordinated migration**:

- Today there is **not yet one human source**. `display_name` is interpolated
  into `device_comment`, while the same human label is duplicated as a literal
  in each live device's `esphome.friendly_name`. Keep those two current values
  aligned. Do not replace `substitutions.friendly_name` with the human label:
  that field prefixes every MQTT entity name and therefore participates in its
  MAC-generated `unique_id`.
- The target model in `naming-architecture.md` makes `display_name` authoritative,
  connects `esphome.friendly_name` and every e-paper text page to it, and gives
  entities function-only names.
- Do **not** rename devices in the HA UI. A UI rename creates the
  `name_by_user` divergence above and survives reflash invisibly.
- Strict typography (accents, `œ`, em-dash `—`, curly apostrophes `’`) belongs in
  the YAML, so the firmware itself carries it and HA needs no override.

### What NOT to touch

`device_name`, `configured_name`, the effective hostname, and the MQTT topic
prefix are **identity**, not display. Changing their effective values renames
topics and breaks the OTA mapping and every retained value. The target changes
the configured representation on six devices but deliberately preserves the
effective runtime value byte-for-byte. Outside that coordinated migration,
display-name work must never alter identity. See `AGENTS.md` for the
identity/topic model and `examples/multi-device/plants.yaml` for the canonical
per-device names.

## Consistency across the fleet

With 8 devices, keep the three display fields consistent per device so nobody has
to re-derive this map each time:

- `substitutions.display_name` = human name with strict typography; currently
  used by `device_comment` and intended to become the sole source.
- `esphome.friendly_name` = an equivalent human name stored as a separate
  current literal; punctuation can already differ. On six devices ESPHome
  currently appends ` mac6`; HA's `name_by_user` masks it.
- `substitutions.friendly_name` = botanical/historical entity prefix and special
  e-paper subtitle. It is deliberately distinct until the coordinated migration.
- `esphome.name` = `${configured_name}` plus the configured suffix behaviour;
  this is technical identity.
- `name_by_user` = currently populated on all eight MQTT devices; the target is
  empty after firmware names are canonical and the canary proves the result.
