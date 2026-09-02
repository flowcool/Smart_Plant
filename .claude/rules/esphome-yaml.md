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
- Every orderly deep-sleep path must call `safe_mode.mark_successful` before
  `deep_sleep.enter` so a healthy first OTA boot is not rolled back.
