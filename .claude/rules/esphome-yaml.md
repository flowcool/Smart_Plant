---
paths:
  - "**/*.yaml"
---

# ESPHome YAML conventions

- `use_address` must be in the `wifi:` block of the device YAML, not only in `substitutions:` — the ESPHome CLI reads YAML without resolving packages.
- Keep the generic `text_sensor: platform: version` diagnostic entity. MQTT
  device-registry `sw_version` and Device Builder deployed metadata may remain
  stale after an ESP-IDF OTA rollback; the retained runtime entity is required
  for operator-visible installed-version checks.
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
- Packages are fetched from GitHub — after pushing changes, clear the package cache on NAS before flashing.
- Production packages rely on ESPHome's native deep-sleep OTA guard
  (`>=2026.8.0`): an orderly `deep_sleep.enter` confirms the app image via
  `on_safe_shutdown` -> `confirm_app_image_`, so `smart_plant_core.yaml` no
  longer calls `safe_mode.mark_successful` (retired in `infra-3rr.47`). The
  public `configuration.yaml` example keeps the explicit call because it targets
  arbitrary ESPHome versions.
- To read deployed fleet ESPHome version, trust the HA discovery config `dev.sw`
  field or the current function-only topic `<mac-prefix>/sensor/esphome_version/state`,
  cross-checked with `esphome/discover/<current-mac-name>`. Legacy per-device
  topics (`<prefix>/sensor/<device>_esphome_version/state`) and legacy/test
  discover names are stale retained orphans and can misreport the version. Use
  `scripts/mqtt_retained.sh` (read-only) rather than re-deriving the auth path.
