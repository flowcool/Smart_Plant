"""Regression tests for the SmartPlant MQTT discovery migration mapping."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "naming_map", ROOT / "scripts/generate_naming_migration_map.py"
)
naming_map = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(naming_map)


class TargetFieldTests(unittest.TestCase):
    def test_oxalis_bench_payload_contract(self):
        """Exact retained ESPHome 2026.7.4 bench payload observed on Oxalis."""
        target = naming_map.target_fields(
            fullmac="4827e25326ba",
            component="sensor",
            node="oxalis-triangularis-5326ba",
            function_label="Air Humidity",
            function_snake="air_humidity",
            domain="sensor",
        )
        self.assertEqual(
            target["new_discovery_topic"],
            "homeassistant/sensor/oxalis-triangularis-5326ba/air_humidity/config",
        )
        self.assertEqual(
            target["new_object_id"],
            "oxalis-triangularis-5326ba_air_humidity",
        )
        self.assertEqual(
            target["new_entity_id"],
            "sensor.oxalis_triangularis_5326ba_air_humidity",
        )
        self.assertEqual(
            target["new_unique_id"],
            "4827e25326ba-sensor-da2b7bfa",
        )

    def test_topic_leaf_is_not_payload_object_id(self):
        target = naming_map.target_fields(
            "4827e254a8f2", "switch", "ceropegia-woodii-54a8f2",
            "Maintenance", "maintenance", "switch",
        )
        self.assertTrue(target["new_discovery_topic"].endswith("/maintenance/config"))
        self.assertNotIn(
            target["new_object_id"], target["new_discovery_topic"].split("/")[-2:]
        )

    def test_all_function_targets_are_collision_free_for_one_device(self):
        targets = [
            naming_map.target_fields(
                "4827e254a8f2", component, "ceropegia-woodii-54a8f2",
                label, snake, "sensor" if component == "sensor" else component,
            )
            for label, snake, component in naming_map.FUNCTIONS
        ]
        for field in (
            "new_discovery_topic", "new_object_id", "new_entity_id", "new_unique_id"
        ):
            self.assertEqual(len({t[field] for t in targets}), 12, field)


if __name__ == "__main__":
    unittest.main()
