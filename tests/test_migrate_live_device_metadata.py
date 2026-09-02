"""Tests for the deterministic live device metadata migration."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "live_metadata", ROOT / "scripts/migrate_live_device_metadata.py"
)
live_metadata = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_metadata)


OLD = """esphome:
  friendly_name: "${display_name}"
substitutions:
  wifi_ssid: !secret wifi_ssid
  device_name: "cyperus-papyrus"
  configured_name: "cyperus-papyrus-54a9b2"
  name_add_mac_suffix: "false"
  botanical_name: "Cyperus papyrus"
  display_name: "Papyrus"
  friendly_name: "Cyperus Papyrus"
  device_comment: "${botanical_name} / ${display_name}"
  ota_password: !secret ota_password
  use_address: "192.0.2.10"
  label_image: "plant_labels/Cyperus_papyrus_label_page_1.png"
packages:
  core: github://flowcool/Smart_Plant/examples/multi-device/packages/smart_plant_core.yaml@V2R1
  transport: github://flowcool/Smart_Plant/examples/multi-device/packages/smart_plant_profile_mqtt.yaml@V2R1
wifi:
  use_address: 192.0.2.10
"""


class LiveMetadataMigrationTests(unittest.TestCase):
    key = "cyperus-papyrus-54a9b2"

    def test_removes_duplicates_and_adds_metadata_package(self):
        new = live_metadata.transform(OLD, self.key)
        self.assertEqual(live_metadata.validate(new, self.key), [])
        self.assertNotIn("esphome:\n", new)
        self.assertNotIn('  display_name: "Papyrus"', new)
        self.assertIn("  wifi_ssid: !secret wifi_ssid", new)
        self.assertIn("  ota_password: !secret ota_password", new)
        self.assertIn("  use_address: \"192.0.2.10\"", new)
        self.assertIn(
            f"  metadata: {live_metadata.metadata_url(self.key)}", new
        )
        self.assertGreater(new.index("  metadata:"), new.index("  transport:"))

    def test_is_idempotent(self):
        once = live_metadata.transform(OLD, self.key)
        self.assertEqual(live_metadata.transform(once, self.key), once)

    def test_preserves_crlf(self):
        old = OLD.replace("\n", "\r\n")
        new = live_metadata.transform(old, self.key)
        self.assertNotIn("\n", new.replace("\r\n", ""))

    def test_check_rejects_old_shape(self):
        errors = live_metadata.validate(OLD, self.key)
        self.assertTrue(any("duplicated" in error for error in errors))
        self.assertTrue(any("metadata package" in error for error in errors))

    def test_check_rejects_metadata_before_core_defaults(self):
        wrong = live_metadata.transform(OLD, self.key)
        metadata = next(line for line in wrong.splitlines() if line.startswith("  metadata:"))
        lines = [line for line in wrong.splitlines() if line != metadata]
        package_index = lines.index("packages:")
        lines.insert(package_index + 1, metadata)
        errors = live_metadata.validate("\n".join(lines) + "\n", self.key)
        self.assertTrue(any("must be last" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
