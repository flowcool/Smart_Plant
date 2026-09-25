---
paths:
  - "**/*.yaml"
---

# ESPHome YAML conventions

- `use_address` must be in the `wifi:` block of the device YAML, not only in `substitutions:` — the ESPHome CLI reads YAML without resolving packages.
- Keep the generic `text_sensor: platform: version` diagnostic entity
  (`hide_hash: false`). Device Builder deployed metadata stays stale after an
  ESP-IDF OTA rollback. The MQTT discovery `dev.sw` and the version entity are
  both retained and republished by the *booted* image on every MQTT connect
  (ESPHome 2026.9.0 `mqtt_client.cpp` on-connect `schedule_resend_state` ->
  `send_discovery_`), so after a rollback they are stale only until that
  image's first connect. `dev.sw` is `<project_version> (ESPHome <ver>)` with a
  static `project_version`, so it cannot distinguish two builds on the same
  ESPHome version; only the entity's `config hash` proves which package
  revision runs.
- Before adding other observability entities, verify HA/ESPHome does not already
  expose the same state and preserve existing MQTT unique IDs.
- MQTT topic prefixes are auto-derived by ESPHome (`name_add_mac_suffix: true`):
  `device_name` + last 3 MAC bytes. Device YAML files set only the botanical
  `device_name`; do not manually include the MAC suffix in `device_name`.
  Exception — duplicate species (same `device_name`) set an explicit unique
  `configured_name` (`<device_name>-<mac6>`) with `name_add_mac_suffix: false`,
  so their node name / hostname / MQTT prefix come verbatim from
  `configured_name` and Device Builder does not collide on identical node names.
- Maintenance commands must be retained and published/subscribed at QoS 1.
- Packages are fetched from GitHub by each build server — after pushing changes, run `scripts/esphome_fleet_update.py reset` (NAS + paired VPS builder) before compiling; a NAS-only purge leaves the VPS clone stale.
- Production packages rely on ESPHome's native deep-sleep OTA guard
  (`>=2026.8.0`): an orderly `deep_sleep.enter` confirms the app image via
  `on_safe_shutdown` -> `confirm_app_image_`, so `smart_plant_core.yaml` no
  longer calls `safe_mode.mark_successful` (retired in `infra-3rr.47`). The
  public `configuration.yaml` example keeps the explicit call because it targets
  arbitrary ESPHome versions.
- To read deployed fleet ESPHome version, trust the HA discovery config `dev.sw`
  field or the current function-only topic `<mac-prefix>/sensor/esphome_version/state`,
  cross-checked with `esphome/discover/<current-mac-name>`. To prove a package
  rollout (same ESPHome version), compare the topic's `config hash` with the
  Device Builder expected hash; `dev.sw` alone is not sufficient. Legacy per-device
  topics (`<prefix>/sensor/<device>_esphome_version/state`) and legacy/test
  discover names are stale retained orphans and can misreport the version. Use
  `scripts/mqtt_retained.sh` (read-only) rather than re-deriving the auth path.
