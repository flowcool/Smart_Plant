# Naming model — how a plant's name flows through the stack

This project has **several independent name fields**. They are easy to confuse:
changing one does not change the others, and one of them (`entity_id`) never
changes again after first discovery. This page is the map. Read it before you
rename anything.

## The name sources

| Field | Where it is set | What it drives | Follows renames? |
|---|---|---|---|
| `substitutions.device_name` | device YAML | ESPHome node name + (with `name_add_mac_suffix`) the **hostname** and **MQTT topic prefix** | — (identity; do not change casually) |
| `substitutions.friendly_name` | device YAML | **every entity name** (`${friendly_name} Temperature`, …) **and** the subtitle text on the maintenance / storage / low-batt e-paper pages (`smart_plant_core.yaml`) | you must edit the YAML |
| `esphome.friendly_name` (`esphome:` block) | device YAML | the device's **suggested name in Home Assistant** | you must edit the YAML |
| `page_1_background` label image | per-device PNG on the NAS (`esphome/plant_labels/`) | the plant name shown on the **normal measurement page** (a rendered image, not text) | regenerate the PNG |
| `name_by_user` | Home Assistant device registry (UI rename, or `ha_set_device`) | the device name shown **in the HA UI**, overriding `esphome.friendly_name` | it *is* the rename — but see the trap below |
| `entity_id` | Home Assistant, **frozen at first discovery** | the entity's stable id (`sensor.<slug>_temperature`) | **never** — set once, then permanent |

## The two traps

1. **`entity_id` is frozen at first discovery.** It is slugified from the name a
   device advertised the *first* time HA saw it. It follows **neither**
   `friendly_name` **nor** `name_by_user` afterwards. Renaming a device leaves
   the old slug in every `entity_id`, automation, and dashboard reference. To
   actually change an `entity_id` you must edit it in HA (or delete + rediscover)
   — deliberately, once.

2. **`name_by_user` is a hidden override.** Renaming a device in the HA UI writes
   `name_by_user`, which *masks* the `esphome.friendly_name` the firmware sends.
   The firmware value is still there, just invisible — until someone clears
   `name_by_user` (a device "reset name"), at which point the UI silently reverts
   to the firmware value. Two sources of truth that only agree by luck.

## The rule: one point of edit

Keep the display name in the **YAML**, and leave `name_by_user` **empty**:

- Set the canonical display name in `esphome.friendly_name` (HA device name) and,
  if you want it on entities / special e-paper pages, in
  `substitutions.friendly_name`.
- Do **not** rename devices in the HA UI. A UI rename creates the
  `name_by_user` divergence above and survives reflash invisibly.
- Strict typography (accents, `œ`, em-dash `—`, curly apostrophes `’`) belongs in
  the YAML, so the firmware itself carries it and HA needs no override.

### What NOT to touch

`device_name`, the derived hostname, and the MQTT topic prefix are **identity**,
not display. Changing them renames topics and breaks the OTA mapping and every
retained value. Display-name work must change only `friendly_name` fields and the
label image — never the identity. See `AGENTS.md` for the identity/topic model
and `examples/multi-device/plants.yaml` for the canonical per-device names.

## Consistency across the fleet

With 8 devices, keep the three display fields consistent per device so nobody has
to re-derive this map each time:

- `esphome.friendly_name` = canonical display name (strict typography).
- `substitutions.friendly_name` = whatever you want on entities + special e-paper
  pages (this project's decision is tracked in the naming-alignment issue).
- `substitutions.display_name` — **unused**; do not add references, remove it when
  aligning.
- `name_by_user` = empty on every device.
