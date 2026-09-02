# Naming model — deployed, staged, and target states

This page is the operational field map for SmartPlant naming. The durable
design and the coordinated Home Assistant migration contract live in
[`naming-architecture.md`](naming-architecture.md). Current execution state and
acceptance evidence live in Beads (`infra-zdxz` and `infra-kl21`), not in this
document.

## Never collapse these three states

| State | What it means | Current naming state |
|---|---|---|
| **Deployed firmware** | What the ESP32 devices are actually running | The eight active entity sets still use the historical coupled names. Six devices still run MAC-suffix application naming; the two Ceropegias already run explicit identity. |
| **Staged NAS configuration** | YAML and label files present in Device Builder but not necessarily compiled or flashed | The eight device YAMLs contain the target explicit identity and `esphome.friendly_name: ${display_name}`, but still duplicate metadata manually. The name-free label PNGs are present. |
| **Repository target** | Source that must be committed, pushed, fetched, compiled, migrated in HA, and flashed before it becomes deployed truth | Generated per-device metadata, function-only entities, node-prefixed payload `obj_id`, clean HA `entity_id`, dynamic e-paper names, and name-free reproducible art. |

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
            ├─ display_name → ESPHome/HA device name + e-paper line 1
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
| `display_name` | Single human/community name source. Drives `esphome.friendly_name` and e-paper line 1. | Yes |
| `secondary_name` | Generated from `botanical_name`, falling back to `horticultural_name`. Drives `device_comment` and e-paper line 2. | Only for a deliberate descriptive rename |
| Entity `name:` | One of 12 fixed function-only literals such as `Temperature` or `Maintenance`. | No |
| Discovery topic leaf | Function snake only, for example `air_humidity`. | No |
| Discovery payload `obj_id` | Dashed node plus function, for example `cyperus-papyrus-54a9b2_air_humidity`. | No |
| HA `entity_id` | HA-sanitized node plus function, for example `sensor.cyperus_papyrus_54a9b2_air_humidity`. | No |
| `name_by_user` | Must be `null` after cutover so it cannot mask the firmware device name. | No independent override |

The obsolete `${friendly_name}` substitution is not part of the target. It
historically prefixed all entity names and therefore changed MQTT `unique_id`
hashes whenever it changed.

## Identity-preserving representation change

For the six historically suffix-enabled devices:

```yaml
# deployed representation
configured_name: "cyperus-papyrus"
name_add_mac_suffix: "true"

# target representation
configured_name: "cyperus-papyrus-54a9b2"
name_add_mac_suffix: "false"
```

Both produce the same runtime node name, hostname, and MQTT prefix:
`cyperus-papyrus-54a9b2`. This is not a topic migration. The two Ceropegias
already use the target representation to avoid a Device Builder collision.

## Home Assistant cutover trap

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

Known pre-cutover cleanup is part of the fleet transaction: Oxalis has a
12-entity orphan set from the bench experiment, and Rhipsalis has an empty
duplicate device-registry row. Neither changes the canary's 12-row scope.

## E-paper naming

The versioned PNGs contain only line art and HA-derived recommended-range arcs.
The firmware renders `display_name` and `secondary_name` dynamically using
Audiowide with `GF_Latin_Core`. A visible rename therefore changes metadata and
text only; it does not change the label path or artwork checksum.

The operator selected the pre-existing 20/15 title sizes. Long names can overlap
the battery/time area; this is an explicitly accepted visual trade-off, not a
claim that every title fits inside that area.

## Pre-flash invariants

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
