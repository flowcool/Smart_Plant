# Device names and screen titles

This guide covers the shared core and the API/MQTT profiles. The standalone
`docs/source/files/configuration.yaml` example has its own substitutions and
image layout. Do not assume it provides the same naming controls.

## Keep identity separate from presentation

| Field | Purpose | Recommendation |
| --- | --- | --- |
| `device_name` | Technical device key. It supplies the default configured name. | Choose a stable lowercase name at installation. Keep it when the plant or room changes. |
| `configured_name` | ESPHome application name before optional MAC suffixing. It also identifies the build directory. | Make it unique for each device that you build together. |
| `name_add_mac_suffix` | Adds a MAC-derived suffix to the runtime name when enabled. | Keep the resulting runtime name stable on installed devices. |
| `display_name` | Full human name. Supplies `esphome.friendly_name`, the diagnostic comment and names on special display pages. | Use a readable plant name. Add a room if people need to distinguish two plants. |
| `screen_title` | Short title on the normal e-paper page only. Defaults to `display_name`. | Override it when the full name is too wide. Keep it meaningful. |
| `secondary_name` | Botanical or cultivar description under the normal-page title. Also appears in the diagnostic comment. | Use the descriptive name that you can support. Do not infer it from an old technical key. |
| Entity `name:` | Measurement or control function, such as `Temperature`. | Keep the package's function-only names. Do not add the plant name to each entity. |

`screen_title` changes no hostname, MQTT topic, entity name, device comment or
Home Assistant device name. It does not change Maintenance, Storage or
low-battery page names. `secondary_name` remains on the second normal-page line.

## Why use separate names?

- A technical identity must survive a room move, a plant replacement or a
  corrected botanical identification. Renaming it can change connection and
  discovery paths.
- A human name can be descriptive. An e-paper title has a fixed space beside
  the battery indicator. A separate title avoids shortening the name in Home
  Assistant just to fit that space.
- A room helps people distinguish two plants. It is a poor permanent device
  key because a device can move.
- Function-only entity names avoid repeating the plant name in every entity.
  In the MQTT profile, ESPHome's MAC-based unique ID includes a hash of the
  entity name. Changing that name can create a new discovery identity.

Do not copy a naming scheme into an existing installation by renaming its
devices or entities. First identify its current runtime names, MQTT discovery
IDs, Home Assistant entity IDs and consumers. A presentation edit and an
identity migration need different validation.

## Configure a short title

Set the substitutions in your device file when you use the shared packages:

```yaml
substitutions:
  device_name: "lemon-tree"
  configured_name: "lemon-tree"
  name_add_mac_suffix: "true"
  display_name: "Lemon Tree - Kitchen"
  screen_title: "Lemon Kitchen"
  secondary_name: "Citrus × limon"
```

Keep the core and exactly one transport profile in `packages:` as shown in the
example device files. Keep credentials in `secrets.yaml`. This snippet changes
the naming fields only; it is not a complete flash configuration.

Omit `screen_title` when `display_name` fits. The shared core uses the full name
as the default. It does not cut or wrap a long title automatically. An explicit
title lets you choose which words remain readable.

The normal page uses Audiowide at size 20 on a 296 × 128 display. Character
count alone cannot prove that text fits: a `W` is wider than an `i`. Use pixel
width as the final check, with room between the title and the battery area.
Check accents and punctuation with the actual firmware font too.

For this layout, the reference title `Peperomia ‘Hope’` measures 191 pixels in
the repository's offline checker. A practical title budget is **18 Unicode
characters and 192 pixels**. These are the local fleet generator's limits,
not an ESPHome or display hardware limit. A different font, font size or
layout needs new measurements. The core itself does not enforce these limits
for manually configured devices.

The local fleet uses these short titles:

| Full human name | Normal-page title | Offline width |
| --- | --- | --- |
| Guirlande de cœurs - Cuisine | Guirlande Cuisine | 191 px |
| Guirlande de cœurs - Séjour | Guirlande Salon | 176 px |
| Plante à monnaie chinoise | Monnaie chinoise | 188 px |
| Peperomia ‘Hope’ | Peperomia ‘Hope’ | 191 px |

The subtitle and time share a separate line. A shorter main title does not
resolve a long botanical subtitle that overlaps the time.

## Give duplicate devices unique build names

Two devices of the same species can share a human name. They must have distinct
technical identities and build artifacts. The runtime MAC suffix alone does
not give two otherwise identical configured names separate build directories.

For new devices, choose distinct stable `configured_name` values. For an
installed device whose runtime name already includes a MAC suffix, you can
represent that exact identity explicitly:

```yaml
substitutions:
  device_name: "lemon-tree"
  configured_name: "lemon-tree-a1b2c3"  # Exact existing runtime name.
  name_add_mac_suffix: "false"
```

Replace the sample with the device's real current name. Do not append a new
suffix or change an existing one. Confirm that the runtime name and MQTT
prefix remain byte-identical before deploying a representation change.

## Local fleet tooling and contribution boundary

The shared core's optional `screen_title` field is reusable on its own. A
generic user does not need the local fleet inventory, generated packages,
Home Assistant registry history or NAS tooling.

The `flowcool` fleet stores its full names and optional short titles in
`plants.yaml`. Its metadata generator validates every title before it writes
any device package. Empty, multiline, overlong and overwide titles fail. The
normal default remains `display_name`; no title is silently abbreviated.

For that inventory, install `label_maker/requirements.txt`, then run from the
repository root:

```bash
python3 scripts/generate_device_metadata.py
python3 scripts/generate_device_metadata.py --check
python3 scripts/preview_screen_titles.py
```

The preview is written to ignored `tmp/screen-titles/fleet.png`. It uses the
checked-in Audiowide font and illustrative battery/time values. It omits live
sensor values and needles. Firmware still obtains Audiowide through ESPHome,
so the preview is an estimate. Verify the real panel on one device before a
fleet deployment.

A generated metadata package must come after the core and transport packages
so its values override the defaults. Do not copy generated naming values back
into a device file; a local substitution can hide later inventory changes.

For a future contribution to the base repository, carry the optional core
field, generic explanation and thin examples. Keep local inventory values,
fleet validation tooling, artwork, operational commands and registry migration
history in the deployment repository. Existing configurations that omit
`screen_title` keep their previous title.
