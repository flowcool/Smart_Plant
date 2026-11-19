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
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "examples/multi-device/plants.yaml"
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}
# Wake times come from the Home Assistant recorder, not MQTT: retained MQTT topics carry no
# timestamp. The recorder stores each battery publish with its arrival time (last_updated_ts).
HA_POSTGRES_CONTAINER = "u-home-automation-hapostgres"
HA_TIMEZONE = "Europe/Paris"
# Mirrors ota_min_battery in smart_plant_core.yaml (a test keeps them equal).
OTA_MIN_BATTERY = 50
# A force_update republish within 10 minutes is the same wake; a gap above 90 minutes is a missed wake.
WAKE_MIN_GAP_S = 600
WAKE_MISSED_GAP_S = 5400
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
    path = "/volume1/docker/home-automation/esphome/config/secrets.yaml"
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.partition(":")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    raise RuntimeError(f"missing {name} in {path}")


topic, payload = sys.argv[1:3]
subprocess.run(
    [
        "docker", "exec", "u-home-automation-eclipse-mosquitto", "mosquitto_pub", "-h", "127.0.0.1",
        "-u", secret("mqtt_username"), "-P", secret("mqtt_password"),
        "-q", "1", "-r", "-t", topic, "-m", payload,
    ],
    check=True,
)
'''

MQTT_READER = r'''import subprocess
import sys


def secret(name):
    path = "/volume1/docker/home-automation/esphome/config/secrets.yaml"
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.partition(":")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    raise RuntimeError(f"missing {name} in {path}")


topics = sys.argv[1:]
command = [
    "docker", "exec", "u-home-automation-eclipse-mosquitto", "mosquitto_sub", "-h", "127.0.0.1",
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


WAKE_SQL = """
with dev as (
  select sm.entity_id, sm.metadata_id from states_meta sm
  where sm.entity_id = any(array[{entities}])
), r as (
  select d.entity_id, s.last_updated_ts ts, s.state,
         s.last_updated_ts - lag(s.last_updated_ts) over (partition by d.entity_id order by s.last_updated_ts) gap
  from dev d join states s on s.metadata_id = d.metadata_id
  where s.last_updated_ts > extract(epoch from now()) - {hours} * 3600
    and s.state ~ '^[0-9.]+$'
)
select entity_id, max(ts),
  (array_agg(state order by ts desc))[1], (array_agg(state order by ts asc))[1],
  coalesce((percentile_cont(0.5) within group (order by gap) filter (where gap > {min_gap}))::text, ''),
  coalesce((stddev(gap) filter (where gap > {min_gap}))::text, ''),
  count(*) filter (where gap > {min_gap}), count(*) filter (where gap > {missed})
from r group by entity_id
"""


def battery_entity(name: str) -> str:
    return "sensor." + name.replace("-", "_") + "_battery"


def parse_wake_rows(output: str, names: list[str]) -> dict[str, dict[str, Any]]:
    by_entity = {battery_entity(name): name for name in names}
    rows: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 8 or parts[0] not in by_entity:
            continue
        median = float(parts[4]) if parts[4] else 3600.0
        rows[by_entity[parts[0]]] = {
            "last": float(parts[1]),
            "battery": float(parts[2]),
            "battery_before": float(parts[3]),
            "median_gap": median,
            "stddev": float(parts[5]) if parts[5] else 0.0,
            "wakes": int(parts[6]),
            "missed": int(parts[7]),
        }
    return rows


def wake_table(
    rows: dict[str, dict[str, Any]], names: list[str], now: float, sort: str
) -> list[str]:
    zone = ZoneInfo(HA_TIMEZONE)

    def clock(epoch: float) -> str:
        moment = datetime.fromtimestamp(epoch, zone)
        today = datetime.fromtimestamp(now, zone).date()
        return moment.strftime("%H:%M" if moment.date() == today else "%m-%d %H:%M")

    entries = []
    for name in names:
        row = rows.get(name)
        if row is None:
            entries.append((name, None))
            continue
        row = dict(row, next=row["last"] + row["median_gap"])
        row["until"] = round((row["next"] - now) / 60)
        entries.append((name, row))
    keys = {
        "next": lambda e: (e[1] is None, e[1]["next"] if e[1] else 0),
        "last": lambda e: (e[1] is None, e[1]["last"] if e[1] else 0),
        "battery": lambda e: (e[1] is None, -(e[1]["battery"]) if e[1] else 0),
    }
    entries.sort(key=keys[sort])
    lines = ["device\tlast_wake\tnext_wake\tin_min\tbattery\tchange\twakes\tmedian_min\tsd_min\tmissed\tota_ok"]
    for name, row in entries:
        if row is None:
            lines.append(f"{name}\tno-data")
            continue
        lines.append("\t".join([
            name, clock(row["last"]), clock(row["next"]), str(row["until"]),
            f"{row['battery']:g}", f"{row['battery'] - row['battery_before']:+g}",
            str(row["wakes"]), f"{row['median_gap'] / 60:.1f}", f"{row['stddev'] / 60:.1f}",
            str(row["missed"]), "yes" if row["battery"] >= OTA_MIN_BATTERY else "no",
        ]))
    return lines


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
                "sudo", "docker", "exec", "u-home-automation-esphome", "python3", "-c",
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
        guard, so the explicit-IP upload flashes a demonstrably awake target
        instead of failing mid-transfer. Returns False on timeout so the caller
        fails loudly, never no-ops silently. Reachability is ground truth here;
        the upload targets the inventory IP directly, so it does not depend on
        Device Builder's discovery cache being correct."""
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

    def compile_one(self, name: str, retries: int) -> None:
        """Distributed compile of one device with bounded cold-build retries.

        Keeps the Ceropegia build-identity collision guard even for a single
        target, so a mis-keyed inventory can never let two devices share one
        artifact. The compile auto-routes to the paired receiver and stages the
        binary back locally for the subsequent explicit-IP upload."""
        self.refuse_unsafe_batch_build([name])
        configuration = self.devices[name]["configuration"]
        for attempt in range(1, retries + 2):
            job = self.api("firmware/compile", {"configuration": configuration})
            result = self.wait_job(job["job_id"])
            if result["status"] == "completed":
                return
            if attempt > retries:
                raise RuntimeError(
                    f"{configuration} compile failed after {attempt} attempt(s): "
                    f"{result.get('error') or result.get('failure_reason') or 'unknown error'}"
                )
            print(f"{configuration}: retrying failed cold build ({attempt}/{retries})")

    def upload_explicit(self, name: str) -> dict[str, Any]:
        """Flash the last-compiled artifact to the device's inventory IP.

        Uploads with an explicit IP (``port=<ip>``): Device Builder forwards it
        verbatim as ``esphome --device <ip>``, bypassing the discovery address
        cache that makes ``firmware/install`` defer against this MQTT-primary
        fleet (runtime_state chronically ``offline`` even while TCP:3232 is up).
        The upload is a standalone job whose own id is waited directly — never a
        dependent adopted from a compile. A non-completed upload raises; there is
        no silent "deferred" success the caller mistakes for a flash."""
        configuration = self.devices[name]["configuration"]
        ip = self.devices[name]["ip"]
        job = self.api(
            "firmware/upload", {"configuration": configuration, "port": ip}
        )
        result = self.wait_job(job["job_id"])
        if result["status"] != "completed":
            raise RuntimeError(
                f"{configuration} upload to {ip} failed: "
                f"{result.get('error') or result.get('failure_reason') or 'unknown error'}"
            )
        return result

    def install(
        self,
        name: str,
        retries: int,
        reachable_timeout: int,
        settle_seconds: int,
    ) -> dict[str, Any]:
        """Compile then explicit-IP upload one device — never firmware/install.

        firmware/install keys its dependent upload on Device Builder's discovery
        cache and defers whenever that cache reads offline, even against a target
        answering TCP:3232 — a silent no-op the caller mistook for a flash. The
        split builds first (device may sleep through the distributed compile),
        then gates on settled OTA reachability and uploads to the inventory IP.
        Compile and upload are distinct results: a compile failure never counts
        as a flash, and a missing upload is an error, not a deferred success."""
        configuration = self.devices[name]["configuration"]
        self.compile_one(name, retries)
        # Gate on settled OTA reachability BEFORE uploading. Hold the device
        # awake (maintenance ON) so its OTA port becomes reachable in time.
        if not self.wait_flashable(name, reachable_timeout, settle_seconds):
            raise RuntimeError(
                f"{configuration}: OTA port not settled-reachable within "
                f"{reachable_timeout}s; refusing to upload (the artifact is built "
                f"but the device is unreachable). Publish maintenance ON to hold "
                f"it awake, then retry."
            )
        return self.upload_explicit(name)

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
        """Arm uploads once OTA reachability + ON hold for the settle guard.

        The fleet is precompiled before maintenance opens, so each ready device
        needs only an upload. Submit it to the inventory IP (bypassing the
        discovery cache that defers firmware/install) as the device settles, so
        uploads run independently while the rest of the fleet is still waking.
        Returns the per-device upload job ids to wait on."""
        deadline = time.monotonic() + timeout_seconds
        settling_since: dict[str, float] = {}
        jobs: dict[str, str] = {}
        pending = set(names)
        while pending and time.monotonic() < deadline:
            statuses = self.maintenance_statuses(list(pending))
            for name in list(pending):
                ready = statuses.get(name) == "ON" and self.is_ota_reachable(
                    self.devices[name]["ip"]
                )
                now = time.monotonic()
                if not ready:
                    settling_since.pop(name, None)
                    continue
                settling_since.setdefault(name, now)
                if now - settling_since[name] < settle_seconds:
                    continue
                configuration = self.devices[name]["configuration"]
                job = self.api(
                    "firmware/upload",
                    {"configuration": configuration, "port": self.devices[name]["ip"]},
                )
                jobs[name] = job["job_id"]
                pending.remove(name)
                print(f"{configuration}: maintenance settled; explicit-IP upload armed")
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
        """Precompile the fleet, then open maintenance and upload each device.

        Every job in ``jobs`` is already a standalone explicit-IP upload (the
        precompile ran before maintenance), so each is waited directly — no
        dependent-upload adoption and no "deferred OTA armed" no-op path."""
        self.compile_many(names, retries)
        self.publish_maintenance(names, "ON")

        jobs: dict[str, str] = {}
        failures: dict[str, str] = {}
        try:
            jobs, failures = self.wait_for_maintenance(
                names, maintenance_timeout, settle_seconds
            )
            for name, job_id in jobs.items():
                upload = self.wait_job(job_id)
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

    def wakes(self, hours: int, sort: str) -> None:
        names = list(self.devices)
        query = WAKE_SQL.format(
            entities=", ".join(f"'{battery_entity(name)}'" for name in names),
            hours=int(hours), min_gap=WAKE_MIN_GAP_S, missed=WAKE_MISSED_GAP_S,
        )
        output = self.ssh([
            "sudo", "docker", "exec", HA_POSTGRES_CONTAINER, "psql", "-U", "ha", "-d", "ha",
            "-At", "-F", "|", "-c", query,
        ])
        print("\n".join(wake_table(parse_wake_rows(output, names), names, time.time(), sort)))

    def status(self) -> None:
        devices = self.api("devices/list")["configured"]
        selected = {row["configuration"]: row for row in devices}
        runtime_groups: dict[str, list[str]] = defaultdict(list)
        for name, values in self.devices.items():
            runtime_groups[str(values["runtime_identity"])].append(name)
        ambiguous_identities = {
            identity for identity, members in runtime_groups.items() if len(members) > 1
        }
        discovery_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in devices:
            configuration = str(row.get("configuration", ""))
            mac = str(row.get("mac_address", ""))
            runtime_ips = row.get("runtime_state", {}).get("ip_addresses", [])
            if mac:
                discovery_groups[("mac", mac)].append(configuration)
            for ip in runtime_ips:
                if ip:
                    discovery_groups[("ip", str(ip))].append(configuration)
        ambiguous_configurations = {
            configuration
            for members in discovery_groups.values()
            if len(set(members)) > 1
            for configuration in members
        }
        for name, values in self.devices.items():
            row = selected.get(values["configuration"], {})
            runtime = row.get("runtime_state", {})
            identity = str(values["runtime_identity"])
            configuration = str(values["configuration"])
            if identity in ambiguous_identities or configuration in ambiguous_configurations:
                state = f"ambiguous(discovery:{identity})"
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
    wakes = subparsers.add_parser("wakes", help="last/next wake, battery and OTA admission per device (HA recorder)")
    wakes.add_argument("--hours", type=int, default=48)
    wakes.add_argument("--sort", choices=["next", "last", "battery"], default="next")
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
    elif args.command == "wakes":
        updater.wakes(args.hours, args.sort)
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
