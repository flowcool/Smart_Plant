# Multi-device OTA maintenance

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
`${maintenance_timeout}` (15 minutes by default). Publishing `ON` again restarts
that timeout.

After the OTA and checks, end maintenance explicitly:

```sh
mosquitto_pub -q 1 -r -t "<mqtt-prefix>/cmd/maintenance" -m "OFF"
```

`OFF` stops the watchdog and enters deep sleep. A timeout also writes retained
`OFF` to both the command and status topics before sleeping, preventing a stale
command from reactivating maintenance at the next wake. A request below the
battery threshold is reset to `OFF`, reports `REJECTED_LOW_BATTERY`, and sleeps.

Always validate one device before a batch OTA. To roll back this package, revert
the package commit, push the branch, purge ESPHome's package cache, and reflash
the last validated firmware over USB if OTA recovery is unavailable.

## Home Assistant control and assisted updates

Home Assistant should expose `<mqtt-prefix>/cmd/maintenance` as a retained QoS 1
MQTT switch and `<mqtt-prefix>/status/maintenance` as a diagnostic sensor. The
switch represents the desired request; the diagnostic sensor shows the result,
including `REJECTED_LOW_BATTERY`. Do not configure MQTT availability for these
entities: retained state must remain visible while the device sleeps.

The recommended update workflow is assisted rather than unattended:

1. Compare the retained running ESPHome version with an operator-selected
   target version and require recent telemetry plus sufficient battery.
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
