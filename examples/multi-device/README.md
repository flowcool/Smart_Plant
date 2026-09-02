# Multi-device OTA maintenance

## Device identity

The repository identity registry is [`plants.yaml`](plants.yaml). Live ESPHome
files remain authoritative for credentials and runtime configuration, while the
registry records the stable mapping operators need when comparing ESPHome,
MQTT, and Home Assistant.

Keep these identity layers separate:

- `device_name` is the immutable lowercase technical slug used by ESPHome; it
  is usually derived from the original botanical identification.
- `mqtt_topic_prefix` is auto-derived by ESPHome from the effective application
  name: the immutable botanical slug plus the last three MAC bytes. Custom
  command and status topics derive from that same runtime prefix.
- `display_name` is the correctly accented French label shown to people; add a
  room after an em dash only when two plants need disambiguation.
- `botanical_name` uses a capitalized genus and lowercase species epithet.
- `device_comment` combines botanical and French labels for diagnostics.

The current live files use three distinct values: `esphome.friendly_name` is the
human MQTT device label, `display_name` is interpolated into `device_comment`,
and the legacy `friendly_name` substitution prefixes entity names and special
e-paper pages. Do not point that legacy substitution at `display_name`: entity
names participate in the MAC-generated MQTT `unique_id`. The locked migration
in [`naming-architecture.md`](../../docs/naming-architecture.md) replaces those
coupled names and migrates the 96 registry identities in place, canary-first.

Do not rename existing device names, MQTT prefixes, entity names, entity IDs,
or discovery unique IDs outside that coordinated migration. It requires
captured MQTT discovery payloads, a generated 96-row old/new map, runtime HA
registry updates, migrated references, and a single-device canary first. The
current installation timezone is intentionally `Europe/Paris`.

The shared soil calibration values are defaults, not evidence that every probe
was individually measured. `plants.yaml` records this explicitly. Unused label
images are inventoried there and intentionally retained.

The shared package performs one measurement/display cycle and then enters deep
sleep for one hour. Battery charge alone never keeps a device awake.

Each device also has a configured ESPHome name. It normally equals
`device_name`, with ESPHome appending the MAC suffix at runtime. When several
physical devices share one botanical `device_name`, set `configured_name`
directly to the already-effective `<device_name>-<mac6>` value and disable
`name_add_mac_suffix`. The effective hostname, MQTT prefix, and discovery
identity stay unchanged, while Device Builder and build directories see unique
names. The fleet helper rejects any remaining duplicate configured name before
starting compilation or Maintenance.

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
missing fuel-gauge reading instead reports `BATTERY_UNAVAILABLE`; it is never
misrepresented as a genuinely low battery. The MAX17043 remains awake across
MCU deep sleep because ESPHome 2026.7.4 provides a sleep action but no matching
wake action, and reliable OTA admission is more important than the gauge's
small software-sleep saving. A successful OTA clears both retained maintenance
states immediately before its automatic reboot and never starts a physical
refresh at that boundary. A normal
reboot performs the normal display refresh; a persisted Storage Mode records a
one-shot pending refresh and restores its page after reboot. Every controlled
refresh waits for the panel's active-high BUSY transition to clear before sleep
or another lifecycle boundary. Failed or abandoned OTA attempts leave
maintenance available for retry until manual `OFF` or the watchdog ends the
window.

Maintenance Status becomes `DISPLAY_REFRESH_FAILED` when the firmware cannot
confirm a complete BUSY HIGH-to-LOW refresh cycle, and OTA readiness is not
published. If BUSY remains high, `DISPLAY_BUSY_TIMEOUT` is reported and the
device refuses deep sleep or a power cut so the panel is not interrupted. A
lightweight recovery loop keeps observing BUSY and resumes safe sleep
automatically 500 ms after the line eventually clears. Every daily Storage wake
reads and publishes a fresh battery value, refreshes the Storage page once, and
keeps temperature, humidity, light, and soil acquisition disabled.

Always validate one device before a batch OTA. To roll back this package, revert
the package commit, push the branch, purge ESPHome's package cache, and reflash
the last validated firmware over USB if OTA recovery is unavailable.

The repeatable operator workflow is implemented by
`scripts/esphome_fleet_update.py`. It reads device identities from
`plants.yaml`, keeps MQTT credentials on the NAS, resets both local and paired
remote build environments through the Device Builder API, retries transient
cold-build failures, and queues deferred OTA installs. Its `update` command
precompiles every selected device before opening any maintenance window, then
waits independently for each device to be online with retained Maintenance
Status `ON`. After a 10-second display-settling guard, it arms that device's
install without making slower devices block ready ones. The default readiness
timeout is 75 minutes, covering one hourly sleep cycle with margin. Run its
`--help` output before use; execute `reset`, then `update` for one canary before
using `update all` for the validated fleet.

Device Builder is the compile scheduler: its firmware API selects a paired
build server, including the VPS offloader. Never use `esphome compile` directly
inside the NAS container for normal operations; that bypasses the distributed
pool and performs the cold build on NAS CPU. Direct container use remains
appropriate for OTA upload of an already-built artifact.

## Boot-cycle arbitration

After MQTT connects, the firmware allows retained command callbacks to run
before it starts acquisition or refreshes the display. `prepare_cycle` then
selects one target state with the fixed priority `Maintenance > Storage Mode >
Normal`; only the acquisition and display path required by that state runs.

| Target state | Acquisition | E-paper action | Sleep behavior |
|---|---|---|---|
| Maintenance | Battery and bounded time synchronization | Show Maintenance once; do not show the normal page first | Prevent deep sleep; 25-minute watchdog |
| Storage Mode, first entry or pending restoration | Battery only | Show Storage once with the current battery level | Sleep for 24 hours |
| Storage Mode, already active | Battery only | Refresh Storage once with the current battery level | Sleep for 24 hours |
| Normal | Battery, temperature, humidity, light, and soil moisture | Show the plant page once | Sleep for one hour |

A Maintenance request is evaluated before Storage Mode even when Storage is
already active. If Maintenance cannot be accepted because the battery is low
or unavailable, the firmware clears the retained request and falls back to the
appropriate Storage or Normal path. When Maintenance ends, the same desired
Storage state determines whether the device restores the Storage page or the
normal plant page. This central arbitration prevents redundant normal-page
refreshes and keeps retained MQTT state, physical display state, and sleep
duration consistent.

## Storage Mode

Storage Mode is a retained seasonal desired state for devices that are not
installed on a plant. Publish commands retained at QoS 1:

```sh
mosquitto_pub -q 1 -r -t "<mqtt-prefix>/cmd/storage_mode" -m "ON"
mosquitto_pub -q 1 -r -t "<mqtt-prefix>/cmd/storage_mode" -m "OFF"
```

The fleet helper keeps broker credentials on the NAS:

```sh
python3 scripts/esphome_fleet_update.py storage ON <device>
python3 scripts/esphome_fleet_update.py storage OFF <device>
```

An accepted `ON` is persisted across deep sleep and broker outages, publishes
retained `ON` to `<mqtt-prefix>/status/storage_mode`, shows the dedicated
Storage Mode page, and changes sleep duration from one hour to 24 hours. Every
daily check reads and publishes the current battery level and refreshes that
page once; plant sensors remain gated. Physical reset does not bypass the
persisted state; retained `OFF` is consumed on the next daily wake and performs
one complete normal display cycle before restoring the one-hour schedule.
Maximum unattended remote exit latency is therefore 24 hours. Maintenance takes
precedence over Storage Mode at a daily wake and returns to the persistent
Storage Mode page when maintenance ends.

The firmware exposes native `Storage Mode` and diagnostic `Storage Mode Status`
entities on the existing MQTT device. Do not override the auto-derived topic
prefix or add the device through Home Assistant's ESPHome integration.

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
