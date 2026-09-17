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
                    "mac_address": "48:27:E2:54:A8:F2",
                    "expected_config_hash": "64ed0af7",
                    "runtime_state": {
                        "state": "offline",
                        "deployed_config_hash": "a45b01fd",
                        "deployed_version": "2026.7.4",
                        "queued_update": False,
                        "ip_addresses": ["192.168.2.235"],
                    },
                },
                {
                    "configuration": "ceropegia-woodii-54a99c.yaml",
                    "mac_address": "48:27:E2:54:A8:F2",
                    "expected_config_hash": "a45b01fd",
                    "runtime_state": {
                        "state": "offline",
                        "deployed_config_hash": "a45b01fd",
                        "deployed_version": "2026.7.4",
                        "queued_update": False,
                        "ip_addresses": ["192.168.2.235"],
                    },
                },
            ]
        }

        with mock.patch("builtins.print") as output:
            self.updater.status()

        cuisine = output.call_args_list[0].args[0].split("\t")
        sejour = output.call_args_list[1].args[0].split("\t")
        self.assertEqual(cuisine[1], "ambiguous(discovery:ceropegia-woodii)")
        self.assertEqual(cuisine[2], "64ed0af7")
        self.assertEqual(cuisine[3:], ["AMBIGUOUS"] * 3)
        self.assertEqual(sejour[2], "a45b01fd")
        self.assertEqual(sejour[3:], ["AMBIGUOUS"] * 3)


class FleetUpdaterExplicitUploadTests(unittest.TestCase):
    """infra-3rr.27: a device update is a distributed compile followed by an
    explicit-IP upload, never firmware/install (whose discovery-cache-keyed
    dependent upload defers against this MQTT-primary fleet)."""

    def setUp(self) -> None:
        self.updater = MODULE.FleetUpdater(
            ssh_target="nas",
            ssh_user="flow",
            ssh_identity="unused",
            receiver_pin="unused",
            poll_seconds=0,
        )
        self.name = "ceropegia-woodii-54a8f2"
        self.configuration = self.updater.devices[self.name]["configuration"]
        self.ip = self.updater.devices[self.name]["ip"]

    def _completed_api(self, calls: list) -> "callable":
        """API stub: compile/upload return a job id; get_job returns completed,
        typed from the job id so wait_job terminates immediately."""

        def api(command: str, args: dict | None = None) -> dict:
            args = args or {}
            calls.append((command, args))
            if command == "firmware/compile":
                return {"job_id": "compile-1"}
            if command == "firmware/upload":
                return {"job_id": "upload-1"}
            if command == "firmware/get_job":
                job_id = args["job_id"]
                job_type = "compile" if job_id.startswith("compile") else "upload"
                return {"job_id": job_id, "job_type": job_type, "status": "completed"}
            raise AssertionError(f"unexpected command {command}")

        return api

    def test_install_compiles_then_uploads_to_explicit_ip(self) -> None:
        calls: list = []
        self.updater.api = self._completed_api(calls)
        self.updater.wait_flashable = lambda *a, **k: True

        result = self.updater.install(
            self.name, retries=2, reachable_timeout=1, settle_seconds=0
        )

        self.assertEqual(result["status"], "completed")
        commands = [command for command, _ in calls]
        # Never the deferring install path; compile precedes upload.
        self.assertNotIn("firmware/install", commands)
        self.assertLess(
            commands.index("firmware/compile"), commands.index("firmware/upload")
        )
        # Exactly one compile — no cold rebuild loop on success.
        self.assertEqual(commands.count("firmware/compile"), 1)
        upload_args = next(a for c, a in calls if c == "firmware/upload")
        self.assertEqual(
            upload_args, {"configuration": self.configuration, "port": self.ip}
        )

    def test_install_refuses_upload_when_not_settled_reachable(self) -> None:
        calls: list = []
        self.updater.api = self._completed_api(calls)
        self.updater.wait_flashable = lambda *a, **k: False

        with self.assertRaisesRegex(RuntimeError, "not settled-reachable"):
            self.updater.install(
                self.name, retries=0, reachable_timeout=1, settle_seconds=0
            )

        commands = [command for command, _ in calls]
        # Compiled (artifact built) but never uploaded to an unreachable device.
        self.assertIn("firmware/compile", commands)
        self.assertNotIn("firmware/upload", commands)

    def test_upload_explicit_failure_raises_never_silent(self) -> None:
        def api(command: str, args: dict | None = None) -> dict:
            args = args or {}
            if command == "firmware/upload":
                return {"job_id": "upload-1"}
            if command == "firmware/get_job":
                return {
                    "job_id": args["job_id"],
                    "job_type": "upload",
                    "status": "failed",
                    "failure_reason": "no route to host",
                }
            raise AssertionError(f"unexpected command {command}")

        self.updater.api = api

        with self.assertRaisesRegex(RuntimeError, "upload to .* failed"):
            self.updater.upload_explicit(self.name)

    def test_wait_for_maintenance_arms_explicit_ip_upload_not_install(self) -> None:
        self.updater.maintenance_statuses = lambda names: {n: "ON" for n in names}
        self.updater.runtime_states = lambda: {self.name: "online"}
        calls: list = []

        def api(command: str, args: dict | None = None) -> dict:
            calls.append((command, args or {}))
            return {"job_id": "upload-1"}

        self.updater.api = api

        jobs, failures = self.updater.wait_for_maintenance(
            [self.name], timeout_seconds=5, settle_seconds=0
        )

        self.assertEqual(jobs, {self.name: "upload-1"})
        self.assertEqual(failures, {})
        commands = [command for command, _ in calls]
        self.assertIn("firmware/upload", commands)
        self.assertNotIn("firmware/install", commands)
        self.assertEqual(
            calls[0][1], {"configuration": self.configuration, "port": self.ip}
        )

    def test_update_many_cleans_up_maintenance_on_upload_failure(self) -> None:
        events: list = []
        self.updater.compile_many = lambda names, retries: events.append(
            ("compile_many", tuple(names))
        )
        self.updater.publish_maintenance = lambda names, state: events.append(
            ("maintenance", state, tuple(names))
        )
        self.updater.wait_for_maintenance = lambda names, t, s: (
            {self.name: "upload-1"},
            {},
        )

        def api(command: str, args: dict | None = None) -> dict:
            if command == "firmware/get_job":
                return {
                    "job_id": "upload-1",
                    "job_type": "upload",
                    "status": "failed",
                    "failure_reason": "boom",
                }
            raise AssertionError(f"unexpected command {command}")

        self.updater.api = api

        with self.assertRaisesRegex(RuntimeError, "partially failed"):
            self.updater.update_many(
                [self.name], retries=2, maintenance_timeout=1, settle_seconds=0
            )

        self.assertIn(("compile_many", (self.name,)), events)
        self.assertIn(("maintenance", "ON", (self.name,)), events)
        # Maintenance is turned back OFF for the failed device on cleanup.
        self.assertIn(("maintenance", "OFF", (self.name,)), events)


if __name__ == "__main__":
    unittest.main()
