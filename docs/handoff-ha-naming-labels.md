# Handoff → Home Assistant agent (project `homeassistant`, epic `infra-kl21`)

**From:** Smart_Plant session, epic `infra-zdxz` / task `infra-zdxz.3` (e-paper labels).
**Date:** 2026-09-02. **Purpose:** make the HA agent aware of what the firmware
side now renders, and state exactly what to validate on the HA registry side so
the two halves of the coordinated naming migration stay consistent.

This brief is derived from `docs/naming-architecture.md` (the locked contract).
Treat that document as authoritative; this is a status + validation checklist,
not a new design.

## 1. What changed on the firmware/display side (zdxz.3)

- The e-paper "normal" page background PNG is now **name-free** (illustration +
  recommended-range arcs only; arcs derived from the one-off kl21.4 HA threshold
  snapshot, no runtime threshold sync).
- The plant name is rendered **dynamically** by ESPHome on the normal page:
  - line 1 = `${display_name}` in `font_title` (Audiowide 20)
  - line 2 = `${botanical_name}` in `font_subtitle` (Audiowide 15)
  - `glyphsets: [GF_Latin_Core]` declared (covers `œ` + French accents; closes
    gate G3). Long names (the two "Guirlande de cœurs …") overlap the battery
    readout — **operator-accepted**, not a bug.
- Core package HEAD: `8a829f8` on `origin/V2R1`. Bench-validated on
  `oxalis-triangularis-5326ba` (Trèfle pourpre) — pinned to tag `zdxz3-bench`
  during the bench, reverts to `@V2R1` after.
- **No entity / unique_id / MQTT topic change comes from zdxz.3.** Labels are a
  display concern only. The 12-entity unique_id migration is entirely kl21's.

## 2. The naming contract (three layers, one source each — §3)

| Layer | Single source | Drives |
|---|---|---|
| Technical identity | `configured_name = <device_name>-<mac6>`, `name_add_mac_suffix: false` | node name, hostname, MQTT topic prefix, discovery `object_id` prefix — **immutable** |
| Device display | `display_name` (FR, strict typography) | `esphome.friendly_name` (HA **device** name), `device_comment`, **e-paper line 1** |
| Entity | function-only literal (ASCII) | entity `name`; with mac6 → MQTT `unique_id`; with node name → `object_id`/clean `entity_id` |

- `display_name` → `esphome.friendly_name`: Unicode is fine here (HA handles it).
- `botanical_name` → e-paper line 2 only (descriptive); it is **not** an HA
  registry field and must **never** couple into an entity name/`unique_id`.
- Entity names stay function-only ASCII; `œ`/accents never reach an entity id
  (G2 dropped — moot). mac6 in every `entity_id` is the uniform target (§3.1).

## 3. Per-device human source of truth (verify HA device names match)

The firmware now renders exactly these strings. HA **device** `name` /
`name_by_user` should equal `display_name` for each:

| configured_name (identity, immutable) | display_name (= HA device name, e-paper line 1) | botanical_name (e-paper line 2) |
|---|---|---|
| ceropegia-woodii-54a8f2 | Guirlande de cœurs - Cuisine | Ceropegia woodii |
| ceropegia-woodii-54a99c | Guirlande de cœurs - Séjour | Ceropegia woodii |
| cyperus-papyrus-54a9b2 | Papyrus | Cyperus papyrus |
| equisetum-hyemale-54a994 | Prêle du Japon | Equisetum hyemale |
| oxalis-triangularis-5326ba | Trèfle pourpre | Oxalis triangularis |
| peperomia-tetraphylla-54a940 | Peperomia ‘Hope’ | **OPEN — not set (see §5)** |
| pilea-peperomioides-54a8e4 | Plante à monnaie chinoise | Pilea peperomioides |
| rhipsalis-baccifera-54a936 | Cactus-gui | Rhipsalis baccifera |

## 4. What to validate on the HA side

1. **Device name consistency.** For each of the 8 devices, HA device registry
   `name` (or `name_by_user`) == the `display_name` above. Flag any mismatch —
   `display_name` is the single human source; HA must not carry a divergent
   literal.
2. **No display coupling into entities.** Confirm no `entity_id` / `unique_id`
   encodes `display_name` (they must be function-only + mac6). This is the whole
   point of the decouple; zdxz.3 does not change it, but validate it still holds
   after your kl21 registry work.
3. **kl21 unique_id migration is orthogonal to zdxz.3.** The label/display
   change touches no MQTT topic or unique_id, so your in-place unique_id
   migration (12 entities × 8 devices) neither blocks nor is blocked by the
   label flash. Sequence them independently; only `display_name` is the shared
   value, and it flows firmware→HA (friendly_name), not the reverse.
4. **Recorder history / Plant bindings** unaffected by zdxz.3 (no entity
   rename from the label change). Your migration remains the only path that
   touches those.

## 5. Open item to resolve (firmware side, needs operator input)

`peperomia-tetraphylla-54a940` device YAML has **no `botanical_name`** → e-paper
line 2 would fall back to the core default. Candidate value: `Peperomia
tetraphylla` (species per the kl21.4 snapshot; `display_name` is the cultivar
"Peperomia ‘Hope’"). Awaiting operator confirmation before the fleet flash. Does
not affect the HA registry side.
