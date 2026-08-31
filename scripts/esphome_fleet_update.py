#!/usr/bin/env python3
"""Run the repeatable Smart Plant ESPHome maintenance/update workflow.

The script talks to the NAS Device Builder API through SSH. Credentials stay on
the NAS: MQTT secrets are read there and are never printed or copied locally.
"""

from __future__ import annotations

import argparse
import base64
import json
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "examples/multi-device/plants.yaml"
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}
DEFAULT_RECEIVER_PIN = "ab350056a3c8251dcf8bd8c9b64ad7d64eca0d8a53f5049f458141d07ba54a01"

WS_CLIENT = r'''import asyncio
import json
import sys

import aiohttp


async def main():
    command = sys.argv[1]
    args = json.loads(sys.argv[2])
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("http://127.0.0.1:6052/ws") as websocket:
            server_info = json.loads((await websocket.receive()).data)
            if server_info.get("requires_auth"):
                raise RuntimeError("Device Builder WebSocket requires authentication")
            await websocket.send_json(
                {"command": command, "message_id": "fleet-update", "args": args}
            )
            while True:
                response = json.loads((await websocket.receive()).data)
                if response.get("message_id") == "fleet-update":
                    print(json.dumps(response))
                    return


asyncio.run(main())
'''

MQTT_PUBLISHER = r'''import subprocess
import sys


def secret(name):
    path = "/volume1/docker/homeassistant/esphome/secrets.yaml"
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.partition(":")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    raise RuntimeError(f"missing {name} in {path}")


topic, payload = sys.argv[1:3]
subprocess.run(
    [
        "docker", "exec", "mqtt", "mosquitto_pub", "-h", "127.0.0.1",
        "-u", secret("mqtt_username"), "-P", secret("mqtt_password"),
        "-q", "1", "-r", "-t", topic, "-m", payload,
    ],
    check=True,
)
'''

MQTT_READER = r'''import subprocess
import sys


def secret(name):
    path = "/volume1/docker/homeassistant/esphome/secrets.yaml"
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.partition(":")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    raise RuntimeError(f"missing {name} in {path}")


topics = sys.argv[1:]
command = [
    "docker", "exec", "mqtt", "mosquitto_sub", "-h", "127.0.0.1",
    "-u", secret("mqtt_username"), "-P", secret("mqtt_password"),
    "-W", "3", "-C", str(len(topics)), "-F", "%t\\t%p",
]
for topic in topics:
    command.extend(["-t", topic])
result = subprocess.run(command, text=True, capture_output=True)
if result.returncode not in (0, 27):
    raise RuntimeError(result.stderr.strip() or f"mosquitto_sub exited {result.returncode}")
print(result.stdout, end="")
'''


def encoded_python(source: str) -> str:
    payload = base64.b64encode(source.encode()).decode()
    return f"import base64;exec(base64.b64decode({payload!r}))"


class FleetUpdater:
    def __init__(
        self,
        ssh_target: str,
        ssh_user: str,
        ssh_identity: str,
        receiver_pin: str,
        poll_seconds: int,
    ) -> None:
        self.ssh_target = ssh_target
        self.ssh_user = ssh_user
        self.ssh_identity = ssh_identity
        self.receiver_pin = receiver_pin
        self.poll_seconds = poll_seconds
        inventory = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))["plants"]
        self.devices = {
            name: {
                "configuration": f"{name}.yaml",
                "build_identity": values.get("configured_name", values["device_name"]),
                "runtime_identity": values.get("configured_name", values["device_name"]),
                "topic": values["mqtt_topic_prefix"],
                "ip": values["ip_address"],
            }
            for name, values in inventory.items()
        }

    def build_identity_collisions(
        self, names: list[str]
    ) -> dict[str, list[str]]:
        """Return selected configurations sharing one ESPHome build identity."""
        groups: dict[str, list[str]] = defaultdict(list)
        for name in names:
            groups[str(self.devices[name]["build_identity"])].append(name)
        return {
            identity: members
            for identity, members in groups.items()
            if len(members) > 1
        }

    def refuse_unsafe_batch_build(self, names: list[str]) -> None:
        """Fail before compilation when artifacts would overwrite each other."""
        collisions = self.build_identity_collisions(names)
        if not collisions:
            return
        details = "; ".join(
            f"{identity}: {', '.join(members)}"
            for identity, members in sorted(collisions.items())
        )
        raise RuntimeError(
            "unsafe batch build: selected configurations share ESPHome build "
            f"identity ({details}). ESPHome would reuse one .esphome/build "
            "directory and may flash the wrong device firmware. Build/install "
            "each colliding configuration separately and verify its per-device "
            "Home Assistant ESPHome Version hash."
        )

    def ssh(self, remote_args: list[str], *, capture: bool = True) -> str:
        command = [
            "ssh", "-F", "/dev/null", "-o", f"User={self.ssh_user}",
            "-o", f"IdentityFile={self.ssh_identity}", "-o", "IdentitiesOnly=yes",
            "-o", f"UserKnownHostsFile={Path.home() / '.ssh/known_hosts'}",
            self.ssh_target, shlex.join(remote_args),
        ]
        result = subprocess.run(command, check=True, text=True, capture_output=capture)
        return result.stdout.strip() if capture else ""

    def api(self, command: str, args: dict[str, Any] | None = None) -> Any:
        output = self.ssh(
            [
                "sudo", "docker", "exec", "esphome", "python3", "-c",
                encoded_python(WS_CLIENT), command, json.dumps(args or {}),
            ]
        )
        response = json.loads(output.splitlines()[-1])
        if "error_code" in response:
            raise RuntimeError(
                f"Device Builder {command}: {response['error_code']}: "
                f"{response.get('details', '')}"
            )
        return response.get("result")

    def wait_job(self, job_id: str) -> dict[str, Any]:
        while True:
            job = self.api("firmware/get_job", {"job_id": job_id})
            if job is None:
                raise RuntimeError(f"Device Builder lost job {job_id}")
            status = job["status"]
            print(f"{job_id}\t{job['job_type']}\t{status}", flush=True)
            if status in TERMINAL_JOB_STATES:
                return job
            time.sleep(self.poll_seconds)

    def reset(self) -> None:
        remote = self.api(
            "remote_build/reset_peer_build_env", {"pin_sha256": self.receiver_pin}
        )
        if self.wait_job(remote["job_id"])["status"] != "completed":
            raise RuntimeError("remote build environment reset failed")
        local = self.api("firmware/reset_build_env")
        if self.wait_job(local["job_id"])["status"] != "completed":
            raise RuntimeError("local build environment reset failed")

    def publish_maintenance(self, names: list[str], payload: str) -> None:
        for name in names:
            topic = f"{self.devices[name]['topic']}/cmd/maintenance"
            self.ssh(
                [
                    "sudo", "python3", "-c", encoded_python(MQTT_PUBLISHER),
                    topic, payload,
                ]
            )
            print(f"{name}\tmaintenance={payload}")

    def publish_storage(self, names: list[str], payload: str) -> None:
        for name in names:
            topic = f"{self.devices[name]['topic']}/cmd/storage_mode"
            self.ssh(
                [
                    "sudo",
                    "python3",
                    "-c",
                    encoded_python(MQTT_PUBLISHER),
                    topic,
                    payload,
                ]
            )
            print(f"{name}\tstorage={payload}")

    def maintenance_statuses(self, names: list[str]) -> dict[str, str]:
        topics = {
            f"{self.devices[name]['topic']}/status/maintenance": name for name in names
        }
        output = self.ssh(
            [
                "sudo",
                "python3",
                "-c",
                encoded_python(MQTT_READER),
                *topics,
            ]
        )
        statuses: dict[str, str] = {}
        for line in output.splitlines():
            topic, separator, payload = line.partition("\t")
            if separator and topic in topics:
                statuses[topics[topic]] = payload
        return statuses

    def runtime_states(self) -> dict[str, str]:
        devices = self.api("devices/list")["configured"]
        by_configuration = {row["configuration"]: row for row in devices}
        return {
            name: str(
                by_configuration.get(values["configuration"], {})
                .get("runtime_state", {})
                .get("state", "unknown")
            )
            for name, values in self.devices.items()
        }

    def is_ota_reachable(self, ip: str) -> bool:
        """Ground-truth flashability: the ESP32 OTA port answers only while the
        device is awake. Device Builder's runtime_state is unreliable for these
        MQTT-primary devices — it reports offline even when the API (6053) and
        OTA (3232) ports are open — so gate on the OTA port directly, per the
        project's OTA-detection convention (nc -z -w1 <ip> 3232). Runs from the
        NAS, which shares the device LAN."""
        out = self.ssh(
            ["sh", "-c", f"nc -z -w1 {shlex.quote(ip)} 3232 && echo OPEN || echo down"]
        )
        return out.strip().endswith("OPEN")

    def wait_flashable(
        self, name: str, timeout_seconds: int, settle_seconds: int
    ) -> bool:
        """Block until the device's OTA port stays reachable for the settle
        guard, so firmware/install runs against a demonstrably awake target and
        produces an upload job instead of arming a deferred queued_update.
        Returns False on timeout so the caller fails loudly, never no-ops
        silently. NOTE: whether firmware/install still defers even against a
        reachable target (Device Builder keying its upload on its own stale
        discovery) is unverified — the bounded upload-adopt + loud raise in
        install() cover that case regardless."""
        configuration = self.devices[name]["configuration"]
        ip = self.devices[name]["ip"]
        deadline = time.monotonic() + timeout_seconds
        reachable_since: float | None = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            if self.is_ota_reachable(ip):
                if reachable_since is None:
                    reachable_since = now
                    print(f"{configuration}: OTA reachable; settling {settle_seconds}s")
                elif now - reachable_since >= settle_seconds:
                    return True
            else:
                reachable_since = None
            time.sleep(self.poll_seconds)
        return False

    def install(
        self,
        name: str,
        retries: int,
        reachable_timeout: int,
        settle_seconds: int,
    ) -> dict[str, Any]:
        configuration = self.devices[name]["configuration"]
        # Gate on settled OTA reachability BEFORE firing. An install against an
        # unreachable/sleeping target compiles but produces no dependent upload
        # job, silently returning a "deferred OTA armed" no-op the caller
        # mistakes for a flash. Hold the device awake (maintenance ON) so its
        # OTA port becomes reachable within the timeout.
        if not self.wait_flashable(name, reachable_timeout, settle_seconds):
            raise RuntimeError(
                f"{configuration}: OTA port not settled-reachable within "
                f"{reachable_timeout}s; refusing to fire install (it would only "
                f"arm a deferred OTA without flashing). Publish maintenance ON to "
                f"hold it awake, then retry."
            )
        for attempt in range(1, retries + 2):
            job = self.api(
                "firmware/install", {"configuration": configuration, "port": "OTA"}
            )
            result = self.wait_job(job["job_id"])
            if result["status"] == "completed":
                # The dependent upload can lag compile completion by a poll or
                # two. Adopt it within a bounded window instead of declaring a
                # deferred no-op on the first miss.
                upload_job = None
                for _ in range(3):
                    jobs = self.api(
                        "firmware/get_jobs", {"configuration": configuration}
                    )
                    uploads = [
                        candidate
                        for candidate in jobs
                        if candidate.get("job_type") == "upload"
                        and candidate.get("depends_on") == job["job_id"]
                    ]
                    if uploads:
                        upload_job = uploads[-1]
                        break
                    time.sleep(self.poll_seconds)
                if upload_job is None:
                    # Online at install time yet still no upload: an anomaly,
                    # not a routine deferral. Fail loudly — never a silent
                    # "compiled" success the caller mistakes for a flash.
                    raise RuntimeError(
                        f"{configuration}: compiled while online but no upload "
                        f"job materialized (a queued_update may be armed); not "
                        f"reported as flashed. Inspect Device Builder discovery."
                    )
                upload = self.wait_job(upload_job["job_id"])
                if upload["status"] != "completed":
                    raise RuntimeError(
                        f"{configuration} upload failed: "
                        f"{upload.get('error') or upload.get('failure_reason') or 'unknown error'}"
                    )
                return upload
            if attempt > retries:
                raise RuntimeError(
                    f"{configuration} compile failed after {attempt} attempt(s): "
                    f"{result.get('error') or result.get('failure_reason') or 'unknown error'}"
                )
            print(f"{configuration}: retrying failed cold build ({attempt}/{retries})")
        raise AssertionError("unreachable")

    def install_many(
        self,
        names: list[str],
        retries: int,
        reachable_timeout: int,
        settle_seconds: int,
    ) -> None:
        for name in names:
            self.install(name, retries, reachable_timeout, settle_seconds)

    def compile_many(self, names: list[str], retries: int) -> None:
        """Precompile every target before opening any maintenance window."""
        self.refuse_unsafe_batch_build(names)
        pending = list(names)
        failures: dict[str, dict[str, Any]] = {}
        for attempt in range(1, retries + 2):
            jobs = {
                name: self.api(
                    "firmware/compile",
                    {"configuration": self.devices[name]["configuration"]},
                )["job_id"]
                for name in pending
            }
            failures = {}
            for name, job_id in jobs.items():
                result = self.wait_job(job_id)
                if result["status"] != "completed":
                    failures[name] = result
            if not failures:
                return
            if attempt <= retries:
                pending = list(failures)
                print(
                    f"retrying {len(pending)} failed precompile(s) "
                    f"({attempt}/{retries})"
                )
        details = ", ".join(
            f"{name}: {result.get('error') or result.get('failure_reason') or result['status']}"
            for name, result in failures.items()
        )
        raise RuntimeError(f"fleet precompile failed; maintenance not enabled: {details}")

    def wait_for_maintenance(
        self,
        names: list[str],
        timeout_seconds: int,
        settle_seconds: int,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Arm installs only after online + ON remain true for the guard."""
        deadline = time.monotonic() + timeout_seconds
        settling_since: dict[str, float] = {}
        jobs: dict[str, str] = {}
        pending = set(names)
        while pending and time.monotonic() < deadline:
            statuses = self.maintenance_statuses(list(pending))
            runtime = self.runtime_states()
            now = time.monotonic()
            for name in list(pending):
                ready = runtime.get(name) == "online" and statuses.get(name) == "ON"
                if not ready:
                    settling_since.pop(name, None)
                    continue
                settling_since.setdefault(name, now)
                if now - settling_since[name] < settle_seconds:
                    continue
                configuration = self.devices[name]["configuration"]
                job = self.api(
                    "firmware/install",
                    {"configuration": configuration, "port": "OTA"},
                )
                jobs[name] = job["job_id"]
                pending.remove(name)
                print(f"{configuration}: maintenance settled; install armed")
            if pending:
                time.sleep(self.poll_seconds)
        return jobs, {name: "maintenance readiness timeout" for name in pending}

    def update_many(
        self,
        names: list[str],
        retries: int,
        maintenance_timeout: int,
        settle_seconds: int,
    ) -> None:
        """Precompile the fleet, then open maintenance and arm every install."""
        self.compile_many(names, retries)
        self.publish_maintenance(names, "ON")

        jobs: dict[str, str] = {}
        failures: dict[str, str] = {}
        try:
            jobs, failures = self.wait_for_maintenance(
                names, maintenance_timeout, settle_seconds
            )
            for name, job_id in jobs.items():
                result = self.wait_job(job_id)
                if result["status"] != "completed":
                    failures[name] = (
                        result.get("error")
                        or result.get("failure_reason")
                        or result["status"]
                    )
                    continue
                configuration = self.devices[name]["configuration"]
                candidates = self.api(
                    "firmware/get_jobs", {"configuration": configuration}
                )
                uploads = [
                    candidate
                    for candidate in candidates
                    if candidate.get("job_type") == "upload"
                    and candidate.get("depends_on") == job_id
                ]
                if not uploads:
                    print(f"{configuration}: compiled; deferred OTA armed")
                    continue
                upload = self.wait_job(uploads[-1]["job_id"])
                if upload["status"] != "completed":
                    failures[name] = (
                        upload.get("error")
                        or upload.get("failure_reason")
                        or upload["status"]
                    )
        except Exception:
            self.publish_maintenance(names, "OFF")
            raise

        if failures:
            self.publish_maintenance(list(failures), "OFF")
            details = ", ".join(f"{name}: {error}" for name, error in failures.items())
            raise RuntimeError(f"fleet update partially failed: {details}")

    def status(self) -> None:
        devices = self.api("devices/list")["configured"]
        selected = {row["configuration"]: row for row in devices}
        runtime_groups: dict[str, list[str]] = defaultdict(list)
        for name, values in self.devices.items():
            runtime_groups[str(values["runtime_identity"])].append(name)
        ambiguous_identities = {
            identity for identity, members in runtime_groups.items() if len(members) > 1
        }
        for name, values in self.devices.items():
            row = selected.get(values["configuration"], {})
            runtime = row.get("runtime_state", {})
            identity = str(values["runtime_identity"])
            if identity in ambiguous_identities:
                state = f"ambiguous(shared-runtime:{identity})"
                deployed_hash = "AMBIGUOUS"
                deployed_version = "AMBIGUOUS"
                queued_update = "AMBIGUOUS"
            else:
                state = str(runtime.get("state", "unknown"))
                deployed_hash = str(runtime.get("deployed_config_hash", "-"))
                deployed_version = str(runtime.get("deployed_version", "-"))
                queued_update = str(runtime.get("queued_update", False))
            print(
                "\t".join(
                    [
                        name,
                        state,
                        str(row.get("expected_config_hash", "-")),
                        deployed_hash,
                        deployed_version,
                        queued_update,
                    ]
                )
            )


def parse_names(updater: FleetUpdater, raw_names: list[str]) -> list[str]:
    if raw_names == ["all"]:
        return list(updater.devices)
    unknown = sorted(set(raw_names) - updater.devices.keys())
    if unknown:
        raise SystemExit(f"unknown device(s): {', '.join(unknown)}")
    return raw_names


def main() -> None:
    # Line-buffer stdout/stderr so progress lines flush immediately when the
    # script is piped (e.g. through tee). Python switches to block buffering
    # by default on non-tty streams, which hides in-flight compile/upload
    # progress for long runs.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh-target", default="192.168.2.117")
    parser.add_argument("--ssh-user", default="flow")
    parser.add_argument(
        "--ssh-identity", default=str(Path.home() / ".ssh/agentvm_to_hosts_ed25519")
    )
    parser.add_argument("--receiver-pin", default=DEFAULT_RECEIVER_PIN)
    parser.add_argument("--poll-seconds", type=int, default=5)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reset")
    subparsers.add_parser("status")
    maintenance = subparsers.add_parser("maintenance")
    maintenance.add_argument("state", choices=["ON", "OFF"])
    maintenance.add_argument("devices", nargs="+", metavar="DEVICE")
    storage = subparsers.add_parser("storage")
    storage.add_argument("state", choices=["ON", "OFF"])
    storage.add_argument("devices", nargs="+", metavar="DEVICE")
    install = subparsers.add_parser("install")
    install.add_argument("devices", nargs="+", metavar="DEVICE")
    install.add_argument("--retries", type=int, default=2)
    install.add_argument("--reachable-timeout", type=int, default=300)
    install.add_argument("--settle-seconds", type=int, default=10)
    update = subparsers.add_parser("update")
    update.add_argument("devices", nargs="+", metavar="DEVICE")
    update.add_argument("--retries", type=int, default=2)
    update.add_argument("--maintenance-timeout", type=int, default=4500)
    update.add_argument("--settle-seconds", type=int, default=10)

    args = parser.parse_args()
    updater = FleetUpdater(
        args.ssh_target,
        args.ssh_user,
        args.ssh_identity,
        args.receiver_pin,
        args.poll_seconds,
    )
    if args.command == "reset":
        updater.reset()
    elif args.command == "status":
        updater.status()
    elif args.command == "maintenance":
        updater.publish_maintenance(parse_names(updater, args.devices), args.state)
    elif args.command == "storage":
        updater.publish_storage(parse_names(updater, args.devices), args.state)
    elif args.command == "install":
        updater.install_many(
            parse_names(updater, args.devices),
            args.retries,
            args.reachable_timeout,
            args.settle_seconds,
        )
    elif args.command == "update":
        updater.update_many(
            parse_names(updater, args.devices),
            args.retries,
            args.maintenance_timeout,
            args.settle_seconds,
        )


if __name__ == "__main__":
    main()
