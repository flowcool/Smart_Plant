# Multi-device OTA maintenance

## Device identity

The repository identity registry is [`plants.yaml`](plants.yaml). Live ESPHome
files remain authoritative for credentials and runtime configuration, while the
registry records the stable mapping operators need when comparing ESPHome,
MQTT, and Home Assistant.

Keep these identity layers separate:

- `device_name` is the immutable lowercase technical slug used by ESPHome; it
  is usually derived from the original botanical identification.
- `mqtt_topic_prefix` is the immutable slug plus the historical MAC suffix.
- `display_name` is the correctly accented French label shown to people; add a
  room after an em dash only when two plants need disambiguation.
- `botanical_name` uses a capitalized genus and lowercase species epithet.
- `device_comment` combines botanical and French labels for diagnostics.

The current live files still use the legacy `friendly_name` substitution for
entity names. `display_name` defines the desired human label in the registry;
do not apply it to existing entities until the canary migration proves that
their MQTT discovery identities remain stable.

Do not rename existing device names, MQTT prefixes, entity names, entity IDs,
or discovery unique IDs as part of a cosmetic cleanup. Such a migration needs
captured MQTT discovery payloads and a single-device canary first. The current
installation timezone is intentionally `Europe/Paris`.

The shared soil calibration values are defaults, not evidence that every probe
was individually measured. `plants.yaml` records this explicitly. Unused label
images are inventoried there and intentionally retained.

The shared package performs one measurement/display cycle and then enters deep
sleep for one hour. Battery charge alone never keeps a device awake.

OTA maintenance uses a retained MQTT desired-state command so a sleeping device
can receive it on its next hourly wake:

```sh
mosquitto_pub -q 1 -r -t "<mqtt-prefix>/cmd/maintenance" -m "ON"
```

The request is accepted only when the measured battery level is at least
`${ota_min_battery}` (50% by default). An accepted device publishes retained
`ON` to `<mqtt-prefix>/status/maintenance` and stays awake for at most
`${maintenance_timeout}` (25 minutes by default). Publishing `ON` again restarts
that timeout. The device shows its friendly name on a minimal maintenance page
with the expected end time; publishing `ON` again refreshes that deadline. If
SNTP time is unavailable, the page shows the remaining duration instead. No
periodic display updates run while the device stays awake.

After the OTA and checks, end maintenance explicitly:

```sh
mosquitto_pub -q 1 -r -t "<mqtt-prefix>/cmd/maintenance" -m "OFF"
```

`OFF` stops the watchdog, restores the normal page once with the latest sensor
readings, and enters deep sleep. A timeout follows the same display path and
writes retained `OFF` to both the command and status topics before sleeping,
preventing a stale command from reactivating maintenance at the next wake. A
request below the battery threshold is reset to `OFF`, reports
`REJECTED_LOW_BATTERY`, and sleeps without showing the maintenance page. A
successful OTA clears both retained maintenance states immediately before its
automatic reboot; the reboot performs the normal display refresh instead of an
extra pre-reboot refresh. Failed or abandoned OTA attempts leave maintenance
available for retry until manual `OFF` or the watchdog ends the window.

Always validate one device before a batch OTA. To roll back this package, revert
the package commit, push the branch, purge ESPHome's package cache, and reflash
the last validated firmware over USB if OTA recovery is unavailable.

The repeatable operator workflow is implemented by
`scripts/esphome_fleet_update.py`. It reads device identities from
`plants.yaml`, keeps MQTT credentials on the NAS, resets both local and paired
remote build environments through the Device Builder API, retries transient
cold-build failures, and queues deferred OTA installs. Its `update` command
precompiles every selected device before opening any maintenance window, then
starts all install jobs so one slow or failed device cannot prevent the others
from being armed. Run its `--help` output before use; execute `reset`, then
`update` for one canary before using `update all` for the validated fleet.

## Home Assistant control and assisted updates

The firmware exposes `Maintenance` and `Maintenance Status` as native ESPHome
MQTT discovery entities. Home Assistant therefore attaches them to the same
MQTT device as the plant sensors. The switch uses the retained QoS 1
`<mqtt-prefix>/cmd/maintenance` contract and represents the desired request;
the diagnostic text sensor uses `<mqtt-prefix>/status/maintenance` and shows
the actual result, including `REJECTED_LOW_BATTERY`. Do not add separate manual
MQTT entities or configure availability: duplicates would be created, and
retained state must remain visible while the device sleeps.

Home Assistant's device information reports the Smart Plant release and ESPHome
core version. The diagnostic ESPHome Version entity also retains ESPHome's native
configuration hash, for example `2026.7.4 (config hash 0x761df8d0)`. This hash
identifies the effective per-device configuration compiled into the image and
can be compared with the corresponding Device Builder artifact. Record the
`config_hash`, source commit, and artifact SHA-256 together in deployment notes.

The recommended update workflow is assisted rather than unattended:

1. Compare the reported configuration hash and ESPHome core version with the
   operator-selected target and require recent telemetry plus sufficient battery.
2. Notify the operator that the device is ready. An accepted notification action
   publishes retained `ON` to the maintenance command topic.
3. Wait until retained maintenance status is `ON`, then compile and upload one
   canary from ESPHome Device Builder.
4. Verify the new running version and at least one complete wake/sleep cycle
   before updating more devices.

If OTA is not started or does not complete, the firmware watchdog clears both
retained maintenance topics and returns the device to deep sleep.

## One-time bootloader migration

ESPHome OTA rollback requires a rollback-capable bootloader, and OTA updates do
not replace the bootloader. Devices that log `Bootloader too old for OTA
rollback` must therefore receive one serial/USB factory flash before relying on
future OTA updates. Use the generated `firmware.factory.bin`, verify one normal
wake/sleep cycle, and only then resume OTA maintenance.

Every orderly sleep path calls `safe_mode.mark_successful` immediately before
deep sleep. This is required because the normal measurement/display cycle can
finish before ESPHome's default 60-second boot validation window; without the
explicit mark, ESP-IDF treats deep sleep as a failed first boot and rolls back to
the previous OTA partition.
