# ESPHome page rendering

The shared core and the public standalone example draw the normal page in
ESPHome. The only image contains the plant illustration. ESPHome draws every
text, icon, ring, recommendation segment, pointer and value. No renderer
selector exists. The page needs no inventory, HA access or threshold messages.

The generic page remains inline in both entry points. The standalone YAML can
be copied without a C++ header or a fleet package. A parity test requires the
normal-page lambdas to remain identical. Their IDs and hardware conventions
are already shared. The original isolated candidate is available in commit
`d0d3510`; it is no longer a third source of drawing code.

## Inputs and preserved meaning

| Input | Purpose | Effect |
| --- | --- | --- |
| `*_recommended_min/max` | Plant care recommendation | Sets the filled ring endpoint |
| `light_max`, `temp_min/max`, `hum_min/max` | Display scale | Sets ring and pointer angles |
| Fixed soil scale `0..100` | Display scale | Sets the soil ring and pointer angles |
| `soil_v_wet/dry` in the sensor configuration | Physical ADC calibration | Converts voltage to soil moisture; not a drawing input |
| `plant_illustration` and `illustration_*` | Plant-only artwork | Sets its source and aspect-fit placement |

HA Plant values remain independent. Align them manually. A display value change
requires a rebuild and a separately authorized deployment. No HA lookup,
threshold MQTT protocol or automatic export exists.

The generic recommendations match the illustrative values in
`docs/source/files/lemon-tree-label.json`. They are not species care advice.
Fleet recommendations and scales are explicit under `display.metrics` in
`plants.yaml`. The metadata generator validates and emits those YAML values.
It does not read the historical HA snapshot. Migration tests compare all 32
recommendations and scales with that snapshot and the old gauge contract.
The legacy `label_image` field remains for historical and printable tooling.

The original renderer fills the ring from 135 degrees to the **midpoint** of
the recommendation. It does not draw the recommendation interval itself.
This meaning is unchanged. The sweep remains 270 degrees. Ring radius/width
remain 22/5 pixels; pointer width remains 7. Origins and value positions stay
unchanged. A zero-width recommendation is valid. A full-scale recommendation
ends at the same angle as a point recommendation at mid-scale.

Finite measurements keep their raw numeric text. Only the pointer is clamped.
Missing and non-finite readings show `--` without a pointer. Invalid fixed
recommendations or scales fail a C++ static assertion during the build.
The battery icon clamps before converting a finite value to an integer.

## Existing text contract

Use the contract in [`../multi-device/NAMING.md`](../multi-device/NAMING.md).
Titles remain one line, Audiowide 20, without automatic cutting or wrapping.
The fleet generator enforces 18 Unicode characters and 192 pixels. The subtitle
remains Audiowide 15 at its existing position. Its known overlap with the clock
is unchanged. Generic users choose a fitting title and subtitle manually.
No new text policy is introduced by this rendering change.

## Reproduce the isolated proof

Use Python with `esphome==2026.10.0`, Pillow, PyYAML and pycairo. Supply an
existing Material Symbols Outlined TTF. Fonts and illustrations are reused.
All generated fixtures, builds and captures stay below ignored project `tmp/`.

```bash
python scripts/prove_drawn_display.py --icon-font /path/to/MaterialSymbolsOutlined.ttf
esphome compile tmp/drawn-display/integrated/host.yaml
esphome compile tmp/drawn-display/integrated/host-standalone.yaml
DRAWN_DISPLAY_HOST="$PWD/tmp/drawn-display/integrated/host-build/.pioenvs/drawn-page-host/program" \
  python -m unittest discover -s tests -p test_drawn_display.py -v
python scripts/prove_drawn_display.py --icon-font /path/to/MaterialSymbolsOutlined.ttf \
  --render-host tmp/drawn-display/integrated/host-build/.pioenvs/drawn-page-host/program
esphome compile tmp/drawn-display/integrated/candidate-api.yaml
esphome compile tmp/drawn-display/integrated/candidate-mqtt.yaml
esphome compile tmp/drawn-display/integrated/standalone.yaml
esphome compile tmp/drawn-display/integrated/baseline-api.yaml
```

The host fixtures execute each entry point's actual page lambda. They use
ESPHome display/font/image code. Only panel transport becomes a pixel buffer.
Host-only controls inject recommendation edge cases and isolate ring ink.
mDNS is disabled. Sensors and time are synthetic; preferences are isolated.

Run the firmware builds sequentially. Parallel ESP-IDF first builds can race
while filling their common temporary component cache. If parallel builds are
needed, set a distinct `ESPHOME_DATA_DIR` for each build. Never reset a live
builder cache for this proof.

ESP32-S2 fixtures keep the real core, transport and sleep logic. Credentials are
synthetic; the broker uses an RFC 5737 address. Compiling never executes that
firmware. The baseline loads the previous core from local commit `d0d3510`.
It uses the same compiler/fonts but different plant artwork. Its resource
comparison is illustrative, not an equal-artwork benchmark.

The script creates eight PNGs, `preview.png` and `render-report.json`. The
report records source, fixture and host executable hashes with observed pixel
writes and host durations. Logs and linked firmware remain in `tmp/`. Beads
owns delivery evidence and the remaining physical acceptance.

## Limits and integration gates

- Binary ring ink differs from Cairo antialiasing. Tests allow one pixel at the
  contour and compare pointer coordinates with the unchanged runtime gauge.
- Gauge icons use Material Symbols instead of PNG silhouettes, at the same
  centres and 22-pixel size. Exact icon bitmaps do not match.
- Long text and extreme raw numbers can overlap adjacent areas. Existing
  fonts, placement and numeric formatting remain unchanged. The proof exposes
  these limits; it does not silently truncate a reading or rename a plant.
- Audiowide lacks 18 glyphs in `GF_Latin_Core`. ESPHome reports them during
  validation. Tested French accents, ligature and `%` render.
- Each refresh visits 4 × 46 × 46 ring candidate pixels. Only annular pixels
  need `atan2`. Firmware adds no screen buffer or ring cache. Linked static RAM
  does not measure peak stack or free heap.
- Host timings are not ESP32 execution, physical refresh or energy measurements.
  Acquisition and deep sleep still need a separately authorized device proof.
  No battery improvement is claimed.

The public Lemon illustration is an unmodified copy from J. G. Aguado's
Label-maker at commit `85648df6982435ec3ca0dfb3d29630e85afb0fc0`, path
`1_Plants/examples/Lemon_tree/Lemon_tree.png`. The generic default URL pins that
source. The copy is `docs/source/images/programming/Lemon_tree.png`.
The existing MIT notice is in `../multi-device/label_maker/LICENSE.Label-maker.txt`.

Keep both legacy generators, their assets and printable-label support until
replacement validation is complete. No historical bitmap is removed or
rewritten. The separate Oxalis canary and its evidence are outside this work.

Before any device action, prepare a separate operation plan. Verify the
plant-only image and fixed YAML values, build one authorized canary, then check
physical normal/inverted rendering, readings, acquisition and deep sleep.
Source integration alone is not physical acceptance or deployment authority.

Local rollback is a revert of the integration commit; commit `d0d3510` retains
the old active pages. No device uses the local integration yet. A later live
rollback also needs the last validated firmware and the project's verified
recovery procedure under its own authority.
