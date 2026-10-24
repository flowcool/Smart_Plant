# ESPHome page proof

This directory contains a local replacement candidate. It is not connected to
the normal shared package or the standalone example. There is no runtime
selector. The existing renderer and label generators remain available.

`page.yaml` owns the title, subtitle, illustration, display scales and care
recommendations. `page.h` draws the gauge geometry. ESPHome draws all text,
icons, rings, pointers and values. The only image is the existing plant
illustration. The candidate uses no fleet inventory or local infrastructure.

## Input contract

| Input | Purpose | Effect |
| --- | --- | --- |
| `*_recommended_min/max` | Plant care recommendation | Sets the filled ring endpoint |
| `light_max`, `temp_min/max`, `hum_min/max` | Display scale | Sets ring and pointer angles |
| Fixed soil scale `0..100` | Display scale | Sets the soil ring and pointer angles |
| `soil_v_wet/dry` in the sensor configuration | Physical ADC calibration | Converts voltage to soil moisture; not read by the page |

HA Plant values remain independent. Align them manually. A display value change
requires a firmware rebuild and a separately authorized deployment. No HA
lookup, threshold MQTT message or automatic export exists.

The example recommendations are synthetic. They are not advice for a species.
Values outside the scale remain visible. Only the pointer is clamped. Missing
and non-finite readings show `--` without a pointer. Invalid configuration
omits the ring and pointer, and shows `--`.

The original artwork fills the ring from 135 degrees to the **midpoint** of the
recommendation. It does not draw the recommendation interval itself. This
candidate preserves that meaning. It preserves the 270-degree sweep, radius
22, ring width 5, pointer width 7, four origins and value positions. A zero-width
recommendation remains valid. A full-scale recommendation has the same endpoint
as a point recommendation at mid-scale.

## Reproduce the local proof

Use Python with `esphome==2026.10.0`, Pillow, PyYAML and pycairo. Use an existing
Material Symbols Outlined TTF for `--icon-font`. No font download is needed.
Build outputs stay below the ignored project `tmp/` directory.

```bash
python scripts/prove_drawn_display.py --icon-font /path/to/MaterialSymbolsOutlined.ttf
esphome compile tmp/drawn-display/proof/host.yaml
DRAWN_DISPLAY_HOST="$PWD/tmp/drawn-display/proof/host-build/.pioenvs/drawn-page-host/program" \
  python -m unittest discover -s tests -p test_drawn_display.py -v
python scripts/prove_drawn_display.py --icon-font /path/to/MaterialSymbolsOutlined.ttf \
  --render-host tmp/drawn-display/proof/host-build/.pioenvs/drawn-page-host/program
esphome compile tmp/drawn-display/proof/candidate-api.yaml
esphome compile tmp/drawn-display/proof/candidate-mqtt.yaml
esphome compile tmp/drawn-display/proof/baseline-api.yaml
```

The host build uses the candidate's actual YAML lambda, header and ESPHome
display/font/image implementations. `tests/drawn_display_host.h` replaces the
panel transport with a pixel buffer. mDNS is disabled. Sensors and clock use
synthetic values. Host preferences use an isolated proof directory.

The ESP32-S2 fixtures use the current shared core and API/MQTT profiles with
synthetic credentials and an RFC 5737 broker address. Compiling does not execute
the firmware. The baseline uses the same fonts, core and compiler. It uses the
existing public Lemon background. Its size comparison is illustrative; it is
not a comparison of equal plant artwork.

The script creates `preview.png`, individual renders and `render-report.json`.
The report binds source and host executable hashes to observed pixel writes and
host durations. Raw build logs and linked firmware stay in `tmp/`. Beads owns
the delivery results and remaining acceptance work.

## Known limits

- Binary ring pixels differ from Cairo's antialiasing. The proof checks that
  ink stays within one pixel of the old contour. Needle coordinates match the
  old C++ calculation exactly in the tested cases.
- Gauge icons use Material Symbols glyphs for water, sunlight, temperature and
  humidity. They replace the old PNG icon shapes. Their centre and 22-pixel
  size remain fixed. The exact bitmap shape is not claimed to match.
- Long titles and subtitles can overlap the clock or battery. The candidate
  preserves the existing placement. Use a short title and check both lines
  before integration. The existing fleet title checker remains unchanged.
  Automatic resizing, truncation and wrapping need a separate layout decision.
- Numeric text keeps the existing font and format. Very large finite readings
  can overlap adjacent areas. The proof exercises this condition. No value is
  silently replaced by its scale endpoint.
- The bundled Audiowide font lacks 18 glyphs in `GF_Latin_Core`. ESPHome reports
  them during validation. The tested French accents, ligature and `%` render.
  Other scripts and unsupported glyphs need separate font qualification.
- Each refresh visits 4 × 46 × 46 ring candidate pixels. Only the annular pixels
  need `atan2`. No extra screen buffer or ring cache is added to the firmware.
  Arrays and formatting still consume stack; the linked RAM report does not
  measure peak stack or free heap.
- Host timings do not measure ESP32 execution, screen refresh, acquisition,
  deep sleep or energy. No battery improvement is claimed.

## Integration and rollback

Keep the old generators, fonts, illustrations, metadata tool and printable
labels until the replacement passes the agreed validation. Do not edit the
separate Oxalis canary or its evidence.

Before integration, copy each accepted scale and recommendation into explicit
device YAML values. Check them against the old offline inputs. Keep calibration
independent. Replace the normal page and full background with this page and an
illustration in one source change. Apply the same generic inputs to the public
standalone example. Do not add a runtime renderer selector.

Resolve long text policy before claiming full layout acceptance. Then use a
separately authorized single-device operation plan to verify physical normal
and inverted pages, readings, acquisition and deep sleep. Do not retire the
e-paper generator or its dependencies before that validation. Inventory tools
and printable-label support retain their own inputs and dependencies.

Local rollback is an atomic revert of this candidate commit. No running device
uses it. A later live integration needs a source revert, the last validated
firmware and the project's verified recovery procedure under its own authority.
