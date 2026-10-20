# Soil sampling interval qualification

## Decision

Keep the existing 3-second interval until a separately authorized bench comparison measures the analog signal. The current evidence does not establish that this interval is required. It also does not establish that 100-200 ms gives equivalent noise rejection.

This is an offline qualification. It changes no firmware, calibration, MQTT value or production device. The source review request is [upstream PR #29](https://github.com/JGAguado/Smart_Plant/pull/29#pullrequestreview-5584638551).

## Evidence and limits

The current `acquire_normal` script in `examples/multi-device/packages/smart_plant_core.yaml` performs five soil ADC updates. Each update is followed by a 3-second delay, including the last update. The programmed dwell is therefore 15 seconds. The first-to-fifth sample span is 12 seconds. Neither number is the complete Wi-Fi-on or boot-to-sleep duration.

The earlier cadence change deliberately preserved inter-measurement spacing while separating AHT20 and VEML7700 acquisition. Its canary evidence is recorded in `infra-3rr.44.6` and merged [fork PR #6](https://github.com/flowcool/Smart_Plant/pull/6). That comparison did not test 100-200 ms spacing. Its accepted HA publication span is a lower-bound proxy, not a measurement of complete awake time.

The exact locally installed ESPHome 2026.9.0 implementation was inspected:

- `components/adc/adc_sensor_esp32.cpp`: `ADCSensor::sample_fixed_attenuation_` reads the configured samples through the synchronous ADC oneshot driver. It does not impose a 3-second interval between component updates.
- `components/sensor/filter.cpp`: `SlidingWindowFilter::new_value` advances on input count. `MedianFilter::compute_result` computes the median of the accepted window. Neither method uses elapsed time to select its output.
- The configured median uses `window_size: 5`, `send_every: 5` and `send_first_at: 5`. It emits after the fifth input. The downstream soil percentage derives from the filtered voltage. No first-sample value is intentionally published.

These software facts explain the sample-count contract. They cannot prove probe settling, noise correlation, switched-supply behavior or unchanged accuracy at a shorter interval. The inspected files are in the existing project-local ESPHome environment; a later implementation must recheck the exact chosen ESPHome build source.

## Candidate timing

For the same five-update loop, including its trailing delay:

| Delay | First-to-fifth span | Programmed dwell |
| --- | ---: | ---: |
| 3 s, current | 12 s | 15 s |
| 200 ms, candidate | 800 ms | 1 s |
| 100 ms, candidate | 400 ms | 500 ms |

Removing only the trailing delay would save 3 seconds without changing sample timestamps. That remains a separate source change: the existing delay also allows asynchronous transport and other components to run. It must be checked against the complete lifecycle before publication.

## Smallest remaining evidence gap

A firmware timing recommendation requires representative analog measurements. Use one spare board and one probe on an isolated bench. Do not use a production device or shared MQTT namespace. This document is a proposal, not authorization to run the bench.

1. Record the board/probe revision, supply voltage, firmware/source version, soil load and power-on age. Include a representative stable load and the post-power-on settling period.
2. Compare paired windows at 3 s, 200 ms and 100 ms. Retain every raw voltage with a relative sample timestamp, the five-sample median and the final calibrated percentage. Repeat the comparison at different battery voltages and representative dry/wet loads. Randomize the order to separate drift from timing.
3. Measure boot-to-deep-sleep duration directly from serial events or supply current. Report it separately from publication span. Compute the possible energy reduction from measured current and duration, not from the programmed delay alone.
4. Check invalid/out-of-range inputs separately with synthetic fixtures. The five-sample publication count and current calibration must remain unchanged. Reject a candidate if it adds a first-sample publication or changes invalid-value handling.
5. Before the bench, agree an acceptable voltage/percentage deviation and repeatability limit from the calibration use case. The existing record reports roughly 8-16 mV intra-device noise; that observation alone is not an acceptance threshold.

Select the longest candidate interval that meets the agreed analog and publication limits. If no candidate meets them, retain 3 seconds and record the observed reason. Any later fleet use needs its own canary/build/OTA authorization and rollback to the last validated firmware.

## Acceptance and rollback

Offline qualification is complete when the source mechanism, timing arithmetic, historical evidence and remaining analog gap are explicit. It does not claim a shorter interval is safe. This document has no runtime effect. Revert its documentation commit to roll it back.
