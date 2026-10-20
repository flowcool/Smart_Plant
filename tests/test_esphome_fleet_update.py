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
        self.updater.runtime_states = lambda: {self.name: "offline"}
        self.updater.is_ota_reachable = mock.Mock(return_value=True)
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


class FleetUpdaterMaintenanceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.updater = MODULE.FleetUpdater("unused", "unused", "unused", "unused", 1)
        self.name = "ceropegia-woodii-54a8f2"
        self.ip = self.updater.devices[self.name]["ip"]
        self.now = 0
        self.clock = mock.patch.object(MODULE.time, "monotonic", lambda: self.now)
        self.sleep = mock.patch.object(MODULE.time, "sleep", self.advance)
        self.clock.start()
        self.sleep.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.sleep.stop)
        # Fail closed if a test misses any external boundary.
        self.updater.ssh = mock.Mock(side_effect=AssertionError("unexpected SSH call"))
        self.updater.runtime_states = mock.Mock(return_value={self.name: "offline"})
        self.updater.maintenance_statuses = mock.Mock(return_value={self.name: "ON"})
        self.updater.is_ota_reachable = mock.Mock(return_value=True)
        self.updater.api = mock.Mock(return_value={"job_id": "upload-1"})

    def advance(self, seconds: int) -> None:
        self.now += seconds

    def test_stale_builder_offline_does_not_block_settled_ota(self) -> None:
        jobs, failures = self.updater.wait_for_maintenance([self.name], 5, 2)

        self.assertEqual(jobs, {self.name: "upload-1"})
        self.assertEqual(failures, {})
        self.assertEqual(self.now, 2)
        self.updater.is_ota_reachable.assert_called_with(self.ip)
        self.updater.runtime_states.assert_not_called()
        self.updater.api.assert_called_once_with(
            "firmware/upload",
            {"configuration": self.updater.devices[self.name]["configuration"], "port": self.ip},
        )

    def test_retained_on_cannot_admit_unreachable_device(self) -> None:
        self.updater.is_ota_reachable.return_value = False
        # Even an optimistic builder state must not admit the target.
        self.updater.runtime_states.return_value = {self.name: "online"}

        jobs, failures = self.updater.wait_for_maintenance([self.name], 3, 0)

        self.assertEqual(jobs, {})
        self.assertEqual(failures, {self.name: "maintenance readiness timeout"})
        self.assertEqual(self.now, 3)
        self.updater.api.assert_not_called()

    def test_reachability_loss_restarts_settle_guard(self) -> None:
        self.updater.is_ota_reachable.side_effect = lambda ip: self.now != 1

        jobs, failures = self.updater.wait_for_maintenance([self.name], 6, 2)

        self.assertEqual(jobs, {self.name: "upload-1"})
        self.assertEqual(failures, {})
        self.assertEqual(self.now, 4)

    def test_maintenance_loss_restarts_settle_guard(self) -> None:
        self.updater.maintenance_statuses.side_effect = lambda names: {
            self.name: "OFF" if self.now == 1 else "ON"
        }

        jobs, failures = self.updater.wait_for_maintenance([self.name], 6, 2)

        self.assertEqual(jobs, {self.name: "upload-1"})
        self.assertEqual(failures, {})
        self.assertEqual(self.now, 4)

    def test_maintenance_ack_is_required_even_when_reachable(self) -> None:
        for status in ({}, {self.name: "OFF"}):
            with self.subTest(status=status):
                self.now = 0
                self.updater.maintenance_statuses.side_effect = None
                self.updater.maintenance_statuses.return_value = status

                jobs, failures = self.updater.wait_for_maintenance([self.name], 3, 0)

                self.assertEqual(jobs, {})
                self.assertIn(self.name, failures)
                self.updater.api.assert_not_called()

    def test_update_timeout_clears_maintenance(self) -> None:
        self.updater.compile_many = mock.Mock()
        self.updater.publish_maintenance = mock.Mock()
        self.updater.is_ota_reachable.return_value = False

        with self.assertRaisesRegex(RuntimeError, "maintenance readiness timeout"):
            self.updater.update_many([self.name], 0, 3, 0)

        self.assertEqual(
            self.updater.publish_maintenance.call_args_list,
            [mock.call([self.name], "ON"), mock.call([self.name], "OFF")],
        )
        self.updater.api.assert_not_called()

    def test_probe_failure_clears_maintenance(self) -> None:
        self.updater.compile_many = mock.Mock()
        self.updater.publish_maintenance = mock.Mock()
        self.updater.is_ota_reachable.side_effect = RuntimeError("probe failed")

        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            self.updater.update_many([self.name], 0, 3, 0)

        self.assertEqual(
            self.updater.publish_maintenance.call_args_list,
            [mock.call([self.name], "ON"), mock.call([self.name], "OFF")],
        )
        self.updater.api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
