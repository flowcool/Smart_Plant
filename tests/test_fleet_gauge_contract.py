"""Check generated scales, Cairo endpoints and actual runtime C++ needles."""
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import yaml

from scripts import generate_device_metadata as metadata
from scripts import smartplant_fleet_gauge_contract as contract
from scripts import smartplant_fleet_label_maker as labels
import test_display_gauge as runtime


ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "examples/multi-device"


def label_command(output, snapshot=contract.SNAPSHOT):
    return [sys.executable, str(ROOT / "scripts/smartplant_fleet_label_maker.py"),
            "--snapshot", str(snapshot), "--plants", str(BASE / "plants.yaml"),
            "--illustrations", str(BASE / "label_maker/illustrations"),
            "--icons", str(BASE / "label_maker/icons"), "--out", str(output)]


class GaugeContractTests(unittest.TestCase):
    # Reuse the C++ recorder, without rerunning the other test class's tests.
    setUpClass = classmethod(runtime.DisplayGaugeTests.setUpClass.__func__)
    render = runtime.DisplayGaugeTests.render

    def test_all_32_midpoints_match_rendered_arc_and_runtime_needle(self):
        snapshot = contract.load_thresholds()
        core = (BASE / "packages/smart_plant_core.yaml").read_text(encoding="utf-8")
        calls = re.findall(
            r"draw_gauge\(id\((\w+)\)\.state,.*?has_state\(\),\s*(.+?),\s*(.+?),\s*(\d+),\s*(\d+),",
            core,
        )
        self.assertEqual(len(calls), 4)
        sensors = {"moisture": "soil", "illuminance": "light",
                   "temperature": "temp", "humidity": "hum"}
        count = 0
        for key in metadata.load_inventory():
            substitutions = yaml.safe_load(metadata.render(
                key, metadata.load_inventory()[key]))["substitutions"]
            thresholds = snapshot[key.rsplit("-", 1)[-1]]["thresholds"]
            for metric, settings in contract.CONTRACT["metrics"].items():
                with self.subTest(device=key, metric=metric):
                    call = next(call for call in calls if call[0] == sensors[metric])
                    def resolve(value):
                        return float(substitutions[value[2:-1]] if value.startswith("${") else value)
                    scale = [resolve(call[1]), resolve(call[2])]
                    expected_scale = contract.full_scale(metric, **{
                        "recommended_min": thresholds[metric]["min"],
                        "recommended_max": thresholds[metric]["max"],
                    })
                    self.assertEqual(scale, expected_scale)
                    position = tuple(map(int, call[3:5]))
                    self.assertEqual(position, tuple(settings["position"]))
                    band = [thresholds[metric]["min"], thresholds[metric]["max"]]
                    # The snapshot is migration evidence only. Fixed YAML is
                    # now the metadata generator's input. Preserve all 32 pairs.
                    prefix = {"moisture": "soil", "illuminance": "light",
                              "temperature": "temp", "humidity": "hum"}[metric]
                    self.assertEqual([float(substitutions[f"{prefix}_recommended_min"]),
                                      float(substitutions[f"{prefix}_recommended_max"])], band)
                    midpoint = sum(band) / 2
                    ctx = Mock()
                    with patch.object(labels, "draw_image"):
                        labels.plot_parameter(ctx, {
                            "rel_range": band, "abs_range": scale,
                            "position": position, "radius": contract.CONTRACT["radius"],
                            "icon": "unused",
                        })
                    endpoint = ctx.arc.call_args_list[0].args[-1]
                    self.assertAlmostEqual(endpoint, contract.angle(midpoint, scale))
                    executed = subprocess.run(
                        [str(self.executable), str(midpoint), "1", *map(str, scale),
                         "%.1f", *map(str, position)],
                        check=True, capture_output=True, text=True,
                    )
                    self.assertAlmostEqual(float(executed.stderr), endpoint, delta=1e-6)
                    # Both outer and inner segment endpoints must agree.
                    self.assertAlmostEqual(ctx.arc_negative.call_args_list[0].args[-2], endpoint)
                    _, lines = self.render(midpoint, *scale, "%.1f", position=position)
                    radius = contract.CONTRACT["radius"]
                    expected_x = position[0] + radius + radius * math.cos(endpoint)
                    expected_y = position[1] + radius + radius * math.sin(endpoint)
                    # Runtime uses float/truncation; Cairo uses double coordinates.
                    self.assertLessEqual(abs(lines[0][0] - expected_x), 1.001)
                    self.assertLessEqual(abs(lines[0][1] - expected_y), 1.001)
                    start = contract.angle(scale[0], scale)
                    self.assertAlmostEqual(ctx.arc.call_args_list[0].args[-2], start)
                    self.assertAlmostEqual((endpoint - start) / math.radians(270),
                                           (midpoint - scale[0]) / (scale[1] - scale[0]))
                    count += 1
        self.assertEqual(count, 32)

    def test_contract_rejects_invalid_or_outside_recommendations(self):
        for metric, minimum, maximum in [
            ("moisture", -1, 50), ("humidity", 20, 101),
            ("temperature", -20, 10), ("illuminance", -1, 6000),
            ("humidity", 70, 20), ("humidity", math.nan, 50),
        ]:
            with self.subTest(metric=metric, minimum=minimum, maximum=maximum):
                with self.assertRaises(ValueError):
                    contract.full_scale(metric, minimum, maximum)

    def test_labels_regenerate_byte_identically(self):
        with tempfile.TemporaryDirectory(prefix="smartplant-labels-") as temporary:
            output = Path(temporary)
            for _ in range(2):
                subprocess.run(label_command(output), check=True, capture_output=True, text=True)
                generated = sorted(output.glob("*.png"))
                self.assertEqual(len(generated), 7)
                for image in generated:
                    self.assertEqual(image.read_bytes(), (BASE / "plant_labels" / image.name).read_bytes())
                    with Image.open(image) as bitmap:
                        self.assertEqual(bitmap.size, tuple(contract.CONTRACT["size"]))
                        self.assertEqual(bitmap.mode, "1")

    def test_shared_filename_with_different_bands_fails_before_rendering(self):
        snapshot = json.loads(contract.SNAPSHOT.read_text(encoding="utf-8"))
        snapshot["by_device_mac6"]["54a99c"]["thresholds"]["moisture"]["min"] += 1
        with tempfile.TemporaryDirectory(prefix="smartplant-label-conflict-") as temporary:
            path = Path(temporary)
            snapshot_path = path / "snapshot.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            output = path / "output"
            result = subprocess.run(label_command(output, snapshot_path), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("conflicting thresholds/scales for shared image", result.stderr)
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
