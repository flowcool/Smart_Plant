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
import time
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
                "topic": values["mqtt_topic_prefix"],
                "ip": values["ip_address"],
            }
            for name, values in inventory.items()
        }

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

    def install(self, name: str, retries: int) -> dict[str, Any]:
        configuration = self.devices[name]["configuration"]
        for attempt in range(1, retries + 2):
            job = self.api(
                "firmware/install", {"configuration": configuration, "port": "OTA"}
            )
            result = self.wait_job(job["job_id"])
            if result["status"] == "completed":
                # An awake target gets a dependent upload immediately. A
                # sleeping target keeps only the completed deferred compile
                # and arms queued_update for its next discovery window.
                jobs = self.api("firmware/get_jobs", {"configuration": configuration})
                uploads = [
                    candidate
                    for candidate in jobs
                    if candidate.get("job_type") == "upload"
                    and candidate.get("depends_on") == job["job_id"]
                ]
                if not uploads:
                    print(f"{configuration}: compiled; deferred OTA armed")
                    return result
                upload = self.wait_job(uploads[-1]["job_id"])
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

    def install_many(self, names: list[str], retries: int) -> None:
        for name in names:
            self.install(name, retries)

    def compile_many(self, names: list[str], retries: int) -> None:
        """Precompile every target before opening any maintenance window."""
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
        for name, values in self.devices.items():
            row = selected.get(values["configuration"], {})
            runtime = row.get("runtime_state", {})
            print(
                "\t".join(
                    [
                        name,
                        str(runtime.get("state", "unknown")),
                        str(row.get("expected_config_hash", "-")),
                        str(runtime.get("deployed_config_hash", "-")),
                        str(runtime.get("deployed_version", "-")),
                        str(runtime.get("queued_update", False)),
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
        updater.install_many(parse_names(updater, args.devices), args.retries)
    elif args.command == "update":
        updater.update_many(
            parse_names(updater, args.devices),
            args.retries,
            args.maintenance_timeout,
            args.settle_seconds,
        )


if __name__ == "__main__":
    main()
