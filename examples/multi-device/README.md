# Multi-device OTA maintenance

The shared package performs one measurement/display cycle and then enters deep
sleep for one hour. Battery charge alone never keeps a device awake.

OTA maintenance uses a retained MQTT desired-state command so a sleeping device
can receive it on its next hourly wake:

```sh
mosquitto_pub -r -t "<mqtt-prefix>/cmd/maintenance" -m "ON"
```

The request is accepted only when the measured battery level is at least
`${ota_min_battery}` (50% by default). An accepted device publishes retained
`ON` to `<mqtt-prefix>/status/maintenance` and stays awake for at most
`${maintenance_timeout}` (15 minutes by default). Publishing `ON` again restarts
that timeout.

After the OTA and checks, end maintenance explicitly:

```sh
mosquitto_pub -r -t "<mqtt-prefix>/cmd/maintenance" -m "OFF"
```

`OFF` stops the watchdog and enters deep sleep. A timeout also writes retained
`OFF` to both the command and status topics before sleeping, preventing a stale
command from reactivating maintenance at the next wake. A request below the
battery threshold is reset to `OFF`, reports `REJECTED_LOW_BATTERY`, and sleeps.

Always validate one device before a batch OTA. To roll back this package, revert
the package commit, push the branch, purge ESPHome's package cache, and reflash
the last validated firmware over USB if OTA recovery is unavailable.
