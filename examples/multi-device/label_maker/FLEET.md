# E-paper gauge inputs

`ha-thresholds-snapshot.json` holds the accepted recommendation bands. Use
`by_device_mac6.<mac6>.thresholds`. The manifest records extraction time,
Home Assistant version and configuration-entry hash. The Rhipsalis record also
records its accepted correction. `number_entity_states_raw` is historical
evidence. It is not a rendering input. No automatic HA refresh runs here.

`fleet-gauge-contract.yaml` defines display geometry and full scales. The two
generators consume the contract through `scripts/smartplant_fleet_gauge_contract.py`.
Humidity and moisture use 0–100%. Temperature uses −10–50°C. Each light scale
ends at the next 5000 lx step that contains its accepted maximum, with a minimum
full scale of 5000 lx. These are display scales, not sensor calibration.

The clockwise screen angle starts at 135° and spans 270°:

```text
angle = 135° + 270° * (clamped_value - minimum) / (maximum - minimum)
```

The filled segment ends at the recommendation midpoint. The runtime needle
uses the same scale and angle. Its number shows the raw finite reading.
The tests compile the runtime C++ lambda and check its coordinates against
the renderer for all 32 device/metric combinations. Core geometry remains
validated against this contract. Generated metadata supplies per-device scales.
Two devices may share a label file only when their recommendation bands and
scales match. The generator checks all filenames before rendering.

Regenerate from the repository root:

```bash
python3 -m pip install -r examples/multi-device/label_maker/requirements.txt
python3 scripts/generate_device_metadata.py
python3 scripts/smartplant_fleet_label_maker.py \
  --snapshot examples/multi-device/label_maker/ha-thresholds-snapshot.json \
  --plants examples/multi-device/plants.yaml \
  --illustrations examples/multi-device/label_maker/illustrations \
  --icons examples/multi-device/label_maker/icons \
  --out examples/multi-device/plant_labels
python3 scripts/generate_device_metadata.py --check
python3 -m unittest discover -s tests -v
```

Run these commands in a Python virtual environment. Rendering needs PyYAML,
Pycairo and Pillow. The runtime test also needs `g++`.
The suite checks PNG bytes against committed outputs and renders twice.
Changing the renderer dependencies can change PNG bytes. Inspect image changes
before accepting a new rendering environment. Tests do not access devices or
compile ESPHome firmware. A real canary build and deployment need separate
authorization.
