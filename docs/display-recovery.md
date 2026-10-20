# Display recovery timing and validation

The package checks the live BUSY pin before normal sleep. If BUSY returns HIGH
after a successful refresh or recovery, it clears the cached safety flag and
starts recovery again. One independent `display_recovery_budget` timer covers
all recovery attempts and the final one-second sleep delays. A successful
sleep request cancels that timer. A new refresh cancels the old recovery,
timer, pending sleep, reset and fault notification before display SPI starts.
Cancellation releases RST if the old reset pulse was still LOW.

With the default 30-second budget, terminal handling reaches
`deep_sleep.enter` within 31.510 seconds for MQTT or 31.010 seconds for API,
plus event-loop scheduling latency, measured from the first recovery start.
This includes the 10 ms reset pulse, 500 ms reset guard and transport fault
notification delay. A failed recovery guard can select terminal handling
earlier. Low-battery sleep has priority over Storage Mode; both retain their
configured durations.

This bound ends at the automation action. It does not prove physical sleep or
zero SPI after a fault. On pinned ESPHome 2026.9.0:

- `deep_sleep/deep_sleep_component.cpp` calls safe-shutdown hooks, then component
  teardown with a 5000 ms budget. The hooks execute before that budget starts.
- `waveshare_epaper/waveshare_epaper.cpp` implements `on_safe_shutdown()` by
  calling the display driver's `deep_sleep()`.
- `WaveshareEPaperTypeA::deep_sleep()` sends command `0x10` and data `0x01` for
  `2.90inv2`, then waits for idle. That model uses the 1000 ms idle timeout.
  The check uses `elapsed > timeout`, so include polling/scheduling overhead.

The YAML terminal path starts no display refresh or SPI operation itself. The
stock driver still sends its sleep command during orderly shutdown. Neither a
strict no-SPI claim nor an exact physical-sleep deadline follows from these
automation tests. The normal shutdown path remains enabled for OTA image
confirmation and orderly network teardown.

Run the isolated regression suite with:

```bash
python3 -m unittest discover -s tests -p 'test_display_recovery*.py' -v
```

The executor reads package YAML and compiles its actual C++ lambdas. It models
only the required automation primitives from ESPHome 2026.9.0. GPIO, time and
transport outputs are local substitutes. Unsupported actions fail the test.
Tests execute the actual refresh-boundary action order from both normal and
maintenance callers. They cover permanent HIGH, guard oscillation, late LOW,
BUSY reassertion during the final sleep delay, cancellation during reset and
notification, fresh budgets, and battery/storage duration priority. They do not
execute the display driver, ESP-IDF, network shutdown or physical hardware.
