# Multi-device ESPHome packages

The example separates hardware and measurement behavior from the Home
Assistant transport:

- `smart_plant_core.yaml` contains the board, sensors, display, Wi-Fi and deep
  sleep behavior.
- `smart_plant_profile_mqtt.yaml` publishes retained MQTT state, so the last
  readings remain visible while the device sleeps.
- `smart_plant_profile_api.yaml` uses only the native ESPHome API. It is simpler,
  but entities become unavailable during deep sleep.

Start from `my-lemon-tree.yaml` for MQTT or `my-lemon-tree-api.yaml` for the
native API, set its substitutions and compose the core with exactly one
transport profile. The API profile clears a Storage latch left by the MQTT
profile and keeps the common low-battery latch. Keep credentials in the local `secrets.yaml`; remote package
files contain no secrets.

The MQTT example preserves an explicit topic prefix. Treat that prefix as a
stable identity after Home Assistant discovery, because changing it creates new
entities.

## Build the checked-out contribution

The example device files fetch remote packages from the production fork's
`V2R1` branch. They do not select this staging contribution automatically.
To validate this checkout, replace the `packages` block in your local device
configuration with local includes. Keep the core and transport from the same
checkout:

```yaml
packages:
  core: !include packages/smart_plant_core.yaml
  transport: !include packages/smart_plant_profile_api.yaml
```

For MQTT, use `packages/smart_plant_profile_mqtt.yaml` as the transport instead.
Keep the device file beside the `packages` directory. Supply its local secrets
and label image before validation. Keep those settings out of commits.

```sh
esphome config examples/multi-device/my-lemon-tree-api.yaml
esphome compile examples/multi-device/my-lemon-tree-api.yaml
```

Use `my-lemon-tree.yaml` for the MQTT variant. These commands validate and build
the selected local packages. They do not upload firmware.

Both profiles use the released `waveshare_epaper` driver and wait for the
panel's physical BUSY cycle before deep sleep. They deliberately keep the
captive portal and Improv Serial recovery paths from the original example; the
captive portal also enables ESPHome's browser-based recovery upload surface.
Deployments that do not need local fallback provisioning can remove
`captive_portal`, `improv_serial`, and the Wi-Fi `ap` block together.

## Low-battery protection

Both transport profiles use the same battery policy. Below 30%, the normal
page changes to white marks on a black background. At or below 15%, the device
shows a critical battery page and sleeps for 24 hours. It keeps this protection
until a valid reading reaches 22% or more. The latch survives deep sleep and
power loss. Charging or changing the battery releases it on the next valid
reading. Missing and non-finite readings do not change the latch.

Override the defaults in the device substitutions:

```yaml
substitutions:
  low_batt_crit_pct: "15"
  low_batt_exit_pct: "22"
  low_batt_warn_pct: "30"
  low_batt_sleep_duration: "24h"
```

Thresholds must satisfy `0 <= critical < exit < warning <= 100`. An invalid
order fails compilation. The long sleep also applies after a panel BUSY fault.
The normal sleep remains one hour. Both paths keep OTA image confirmation and
the existing display completion or emergency reset sequence before sleep.
This feature does not require MQTT or Home Assistant commands.

This upstream staging contribution keeps the baseline's explicit
`safe_mode.mark_successful` action before both sleep paths. It does not declare
the production fork's ESPHome `>=2026.8.0` requirement. Production can rely on
native image confirmation under that requirement. The offline tests check the
explicit action's ordering; they do not simulate bootloader confirmation.
Complete local API and MQTT builds verify action availability with ESPHome
2026.9.0. Older ESPHome versions were not compiled in this review.

## Retained MQTT controls

These controls belong to the MQTT profile. The API profile keeps the normal
measurement cycle. Compose the core and profile from the same revision.

Publish `ON` or `OFF` with retain enabled and QoS 1:

| Control | Command topic | Result topic |
| --- | --- | --- |
| Maintenance | `<prefix>/cmd/maintenance` | `<prefix>/status/maintenance` |
| Storage | `<prefix>/cmd/storage_mode` | `<prefix>/status/storage_mode` |

`<prefix>` is `mqtt_topic_prefix`. Command state expresses the requested mode.
Result state expresses the accepted mode. Home Assistant discovers both
controls and their diagnostic result entities.

Maintenance has priority over Storage. Admission requires a finite battery
reading at or above `ota_min_battery` (50% by default). A lower reading returns
`REJECTED_LOW_BATTERY`; a missing or non-finite reading returns
`BATTERY_UNAVAILABLE`. Both results clear the retained Maintenance command.
A rejected request resumes Storage or acquires fresh plant readings for Normal
mode. The rejection result remains visible through that cycle.
Maintenance samples only the battery. Its page shows the window end time when
the clock is valid. A missing clock delays admission by at most ten seconds.

Wait for Maintenance result `ON` before uploading firmware. This result follows
an observed panel BUSY HIGH-to-LOW refresh cycle and its settling guard. A
physical LOW without an observed assertion does not acknowledge readiness.
A repeated `ON` renews the window. `OFF` or the watchdog clears the retained
command, restores the selected mode and refreshes the display. Normal mode
first acquires fresh plant measurements. Changed requests received during
acquisition or display settlement cancel the older work; the latest requested
state wins. An echoed Maintenance `OFF` after rejection or exit starts no new
cycle. Equal Storage requests do not restart pending work. Maintenance `ON`
continues to renew its timed window.

A successful OTA transfer clears the Maintenance request and cancels its
watchdog before a two-second MQTT flush. It starts no new display refresh.
When Storage was active, a persisted flag requests its page on the next boot.
A failed transfer leaves the current window under its watchdog.

Storage persists in NVS. Each Storage wake samples only the battery, refreshes
the Storage page and sleeps for 24 hours. It keeps this behavior if the broker
is unavailable. Retained `OFF` restores normal acquisition on the next wake;
this can take up to the configured Storage sleep interval. A Storage command
received during Maintenance takes effect when Maintenance ends.

Low-battery protection keeps priority over the Storage page and sleep duration.
The common core remains independent of MQTT commands. Both normal and emergency
sleep paths explicitly confirm the OTA image before shutdown.

```yaml
substitutions:
  ota_min_battery: "50"
  maintenance_timeout_minutes: "25"
  storage_sleep_duration: "24h"
```

Panel recovery uses one total 30-second budget across BUSY retries. A terminal
fault increments a persisted counter, resets the panel, waits for the reset
guard and enters emergency sleep. The MQTT profile publishes the counter at
`<prefix>/status/display_fault_count`. A new refresh cancels all delayed work
from the previous refresh. ESPHome still runs its native shutdown handlers.

Run the offline package tests with `python3 -B -m unittest discover -s tests -v`.
They execute the package actions and compile the policy lambdas as C++ with
simulated sensors, time and GPIO. Firmware compilation checks ESPHome schemas
and generated code. Neither check proves physical panel or network behavior.
