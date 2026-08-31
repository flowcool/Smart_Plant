import importlib.util
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "esphome_fleet_update.py"
SPEC = importlib.util.spec_from_file_location("esphome_fleet_update", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FleetUpdaterBuildIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.updater = MODULE.FleetUpdater(
            ssh_target="nas",
            ssh_user="flow",
            ssh_identity="unused",
            receiver_pin="unused",
            poll_seconds=0,
        )

    def test_inventory_isolates_ceropegia_configured_names(self) -> None:
        collisions = self.updater.build_identity_collisions(
            ["ceropegia-woodii-54a8f2", "ceropegia-woodii-54a99c"]
        )

        self.assertEqual(collisions, {})
        self.assertNotEqual(
            self.updater.devices["ceropegia-woodii-54a8f2"]["build_identity"],
            self.updater.devices["ceropegia-woodii-54a99c"]["build_identity"],
        )

    def test_batch_build_refuses_duplicate_identity_before_api_call(self) -> None:
        self.updater.devices["ceropegia-woodii-54a99c"]["build_identity"] = (
            self.updater.devices["ceropegia-woodii-54a8f2"]["build_identity"]
        )
        self.updater.api = lambda *_args, **_kwargs: self.fail(
            "Device Builder API must not be called for an unsafe batch"
        )

        with self.assertRaisesRegex(RuntimeError, "unsafe batch build"):
            self.updater.compile_many(
                ["ceropegia-woodii-54a8f2", "ceropegia-woodii-54a99c"],
                retries=0,
            )

    def test_single_configuration_remains_buildable(self) -> None:
        self.assertEqual(
            self.updater.build_identity_collisions(["ceropegia-woodii-54a8f2"]),
            {},
        )
        self.updater.refuse_unsafe_batch_build(["ceropegia-woodii-54a8f2"])

    def test_status_hides_ambiguous_device_builder_runtime_hashes(self) -> None:
        for name in (
            "ceropegia-woodii-54a8f2",
            "ceropegia-woodii-54a99c",
        ):
            self.updater.devices[name]["runtime_identity"] = "ceropegia-woodii"
        self.updater.api = lambda *_args, **_kwargs: {
            "configured": [
                {
                    "configuration": "ceropegia-woodii-54a8f2.yaml",
                    "expected_config_hash": "64ed0af7",
                    "runtime_state": {
                        "state": "offline",
                        "deployed_config_hash": "a45b01fd",
                        "deployed_version": "2026.7.4",
                        "queued_update": False,
                    },
                },
                {
                    "configuration": "ceropegia-woodii-54a99c.yaml",
                    "expected_config_hash": "a45b01fd",
                    "runtime_state": {
                        "state": "offline",
                        "deployed_config_hash": "a45b01fd",
                        "deployed_version": "2026.7.4",
                        "queued_update": False,
                    },
                },
            ]
        }

        with mock.patch("builtins.print") as output:
            self.updater.status()

        cuisine = output.call_args_list[0].args[0].split("\t")
        sejour = output.call_args_list[1].args[0].split("\t")
        self.assertEqual(cuisine[1], "ambiguous(shared-runtime:ceropegia-woodii)")
        self.assertEqual(cuisine[2], "64ed0af7")
        self.assertEqual(cuisine[3:], ["AMBIGUOUS"] * 3)
        self.assertEqual(sejour[2], "a45b01fd")
        self.assertEqual(sejour[3:], ["AMBIGUOUS"] * 3)


if __name__ == "__main__":
    unittest.main()
