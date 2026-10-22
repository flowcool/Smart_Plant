# Naming model — deployed contract and historical cutover notes

This page is the operational field map for SmartPlant naming. The coordinated
cutover completed on 2026-09-03; acceptance evidence lives in closed Beads epics
`infra-zdxz` and `infra-kl21`. The executed migration design and pre-cutover
evidence remain in [`naming-architecture.md`](naming-architecture.md).

For reusable choices, rationale and user examples, read
[Device names and screen titles](../examples/multi-device/NAMING.md).
That guide separates the optional core field from this deployment's inventory
and migration history. The short-title source change does not itself deploy
firmware or require a Home Assistant registry migration.

## Current deployed state

| Surface | Current naming state | Authority |
|---|---|---|
| **Technical identity** | All eight devices use explicit `<device_name>-<mac6>` configured names with `name_add_mac_suffix: false`; hostname and MQTT prefix stayed byte-identical through the cutover. | `plants.yaml` plus generated metadata |
| **Human display** | `display_name` drives firmware metadata and e-paper text. Home Assistant keeps `name_by_user` to preserve French typography that the ASCII firmware name cannot reproduce exactly. | `plants.yaml` and HA device registry |
| **Entities** | Eleven exposed entity names are function-only. HA entity IDs carry the MAC-bearing node identity; obsolete rows, statistics, retained discovery, and consumers were reconciled during the cutover. | Firmware packages and HA registries |

A clean repository, a Device Builder `deployed_config_hash`, or a staged YAML is
not deployment evidence. Confirm the running ESPHome Version entity, runtime
logs, discovery payloads, and a complete wake/sleep cycle after flashing.

## Target data flow

`examples/multi-device/plants.yaml` is the only hand-edited source for
per-device identity and visible names:

```text
plants.yaml
  └─ scripts/generate_device_metadata.py
       └─ packages/generated/<configured_name>.yaml
            ├─ configured_name + suffix mode → node/hostname/MQTT identity
            ├─ display_name → ESPHome/HA device name + special-page names
            ├─ screen_title (display_name fallback) → normal e-paper line 1
            └─ secondary_name → comment + e-paper line 2

function-only entity names
  ├─ FNV-1(name) + full MAC + component → MQTT unique_id
  ├─ function snake → discovery-topic leaf and state-topic object
  └─ node + function → discovery payload obj_id → clean HA entity_id
```

Production device YAMLs must import their matching generated metadata package.
They retain secrets, package references, and their network/`use_address`
configuration; they must not duplicate naming literals.

## Field contract

| Field | Target owner and role | Human rename changes it? |
|---|---|---|
| `device_name` | Historical opaque identity key. Do not reinterpret or rename it. | No |
| `configured_name` | Exact already-effective `<device_name>-<mac6>` node identity. | No |
| `name_add_mac_suffix` | `false` on all eight production devices because the suffix is frozen inside `configured_name`. | No |
| `mqtt_topic_prefix` | Must equal `configured_name`; listed in inventory as the identity invariant. | No |
| `display_name` | Full human/community name. Drives `esphome.friendly_name` and the maintenance/storage/low-battery page names. | Yes |
| `screen_title` | Optional short title for normal e-paper line 1 only. Falls back to `display_name`. Does not affect HA, MQTT, or device identity. | Screen title edit only |
| `secondary_name` | Generated from `botanical_name`, falling back to `horticultural_name`. Drives `device_comment` and e-paper line 2. | Only for a deliberate descriptive rename |
| Entity `name:` | One of 12 fixed function-only literals such as `Temperature` or `Maintenance`. | No |
| Discovery topic leaf | Function snake only, for example `air_humidity`. | No |
| Discovery payload `obj_id` | Dashed node plus function, for example `cyperus-papyrus-54a9b2_air_humidity`. | No |
| HA `entity_id` | HA-sanitized node plus function, for example `sensor.cyperus_papyrus_54a9b2_air_humidity`. | No |
| `name_by_user` | Kept in HA only to preserve exact French typography; it must describe the same plant as `display_name`, not create an independent identity. | Coordinated display rename only |

The obsolete `${friendly_name}` substitution is not part of the deployed model. It
historically prefixed all entity names and therefore changed MQTT `unique_id`
hashes whenever it changed.

## Identity-preserving representation change

For the six historically suffix-enabled devices:

```yaml
# deployed representation
configured_name: "cyperus-papyrus"
name_add_mac_suffix: "true"

# deployed representation
configured_name: "cyperus-papyrus-54a9b2"
name_add_mac_suffix: "false"
```

Both produce the same runtime node name, hostname, and MQTT prefix:
`cyperus-papyrus-54a9b2`. This is not a topic migration. The two Ceropegias
use this representation, including the duplicate Ceropegias.

## Historical Home Assistant cutover trap (completed)

The remainder of this section records the pre-cutover constraints and the
transaction that was executed. It is evidence, not a current procedure. Any
future identity change requires a new owner, fresh registry captures, and a new
rollback plan.

Changing the 12 entity names from historical prefixes to function-only literals
changes all 12 MQTT `unique_id` hashes per device. Flashing without the
coordinated HA migration creates replacement entities and strands recorder
history and consumers.

The canary transaction therefore owns one device and exactly 12 history-bearing
rows:

1. capture the current retained discovery payloads and HA registries;
2. put the 12 old discovery payloads into migration mode;
3. update `unique_id` and `entity_id` together through HA's runtime registry API;
4. flash the matching firmware during the same awake window;
5. confirm the new payloads reattach to the same rows and device;
6. migrate consumers, clear the exact old topics, and clear `name_by_user`;
7. verify recorder continuity, telemetry, controls, logs, and sleep.

The migration map must keep these different values separate:

```text
topic:     homeassistant/sensor/<node>/air_humidity/config
obj_id:    <node>_air_humidity
entity_id: sensor.<node_with_underscores>_air_humidity
```

Known pre-cutover cleanup is part of the fleet transaction. Oxalis is a special
case: it was already flashed to the target firmware during the `infra-zdxz.3`
bench, so its HA device now carries **two** retained 12-entity MQTT sets at once
(verified read-only 2026-09-03 in `core.entity_registry`: 24 enabled rows on one
device):

- the coupled deployed set (`unique_id 4827e25326ba-*-53accb91…`, entity_id
  `sensor.sejour_oxalis_triangularis_oxalis_triangularis_*`) holds the ~6.5
  months of recorder history since 2026-02-14. It is the history-bearing AS-IS
  set the canary must preserve, **not** a disposable orphan; it only froze when
  the target firmware took over;
- the target-firmware set (`unique_id 4827e25326ba-*-da2b7bfa…` — the exact
  `new_unique_id` values from the 96-row map, entity_id
  `sensor.sejour_trefle_pourpre_*`) is a pre-2026-02 orphan **revived** by the
  bench flash: live, but bound to the wrong (old, frozen) entity_id.

Consequence: on Oxalis the 12 target `unique_id`s are **already occupied**, so the
plain §4 in-place `unique_id` migration does not apply directly — the target ids
must be freed/reassigned as part of the HA reconciliation (mechanism owned by kl21).
This **does** change the migration path for Oxalis — see the constraints in
`naming-architecture.md` §4.2. The other seven devices are in the clean single-set
pre-cutover state and follow the §4 contract unchanged (verified: 0/12 target
`unique_id`s present in the registry for each). Rhipsalis still has an empty
duplicate device-registry row, which does not affect the 12-row scope.

## E-paper naming

The versioned PNGs contain only line art and HA-derived recommended-range arcs.
The firmware renders `screen_title` and `secondary_name` dynamically using
Audiowide with `GF_Latin_Core`. A visible rename therefore changes metadata and
text only; it does not change the label path or artwork checksum.

The title/subtitle sizes remain 20/15. The normal-page title has a separate
`screen_title` override in `plants.yaml`. Omit it when `display_name` fits.
The metadata generator rejects empty titles, control characters, titles over
18 Unicode characters, and titles wider than 192 pixels in the checked-in
Audiowide size 20 font. It validates every device before writing any packages.
It does not silently shorten names.

The width reference is `Peperomia ‘Hope’` (191 pixels with the offline checker).
The 192-pixel limit also fits `Guirlande Cuisine` (191 pixels). The other
short overrides are `Guirlande Salon` and `Monnaie chinoise`. The full
`display_name`, secondary botanical name, identities and entity names stay intact.

Run `python3 scripts/generate_device_metadata.py --check` to check the inputs
and generated packages. Install the existing label-maker requirements first.
Run `python3 scripts/preview_screen_titles.py` for an eight-device preview in
ignored `tmp/screen-titles/fleet.png`. Previews use illustrative battery/time
values and omit live sensor values. Firmware still fetches Audiowide through
ESPHome; verify the canary render before deployment. The subtitle/time layout
is unchanged and can still overlap for long botanical names.

## Historical pre-flash invariants

- `configured_name == mqtt_topic_prefix` for all eight devices;
- every production YAML consumes its matching generated metadata package;
- generated metadata and naming regression tests are clean;
- all 12 exposed entity names are fixed function-only literals;
- the 96-row map validates topic, payload `obj_id`, `entity_id`, and `unique_id`
  independently;
- the package and build caches were reset after the final pushed commit;
- the canary has fresh HA/MQTT/YAML backups and a known-good rollback image;
- only the coordinated HA migration and matching firmware flash share the
  canary transaction.
