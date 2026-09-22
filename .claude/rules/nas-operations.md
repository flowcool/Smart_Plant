# NAS and OTA operations

- NAS access is **read-only by default**. Write only when explicitly confirmed by the user.
- **Validate one device before batch OTA.** Confirm the running version in HA,
  inspect device runtime logs for rollback, and observe at least two subsequent
  wake/sleep cycles. Device Builder's stored deployed hash is not authoritative
  after rollback.
- **Clean rollback before moving on.** When rollback is requested, fully restore state and confirm before proceeding with new work.
- `Bootloader too old for OTA rollback` requires one serial USB factory flash;
  an OTA upload does not update the bootloader.
- ESPHome's native guard (`>=2026.8.0`) confirms the app image on any orderly
  `deep_sleep.enter`, so a short measurement cycle is no longer misclassified as
  a failed OTA boot; `smart_plant_core.yaml` no longer calls
  `safe_mode.mark_successful` (retired in `infra-3rr.47`; the public
  `configuration.yaml` example keeps it for version-agnostic safety).
- OTA detection: `nc -z -w1 <ip> 3232` — ICMP ping is unreliable on ESP32.
- Flash: `docker exec esphome esphome upload /config/<device>.yaml --device <ip>`
