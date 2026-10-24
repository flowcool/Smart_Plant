#!/usr/bin/env python3
"""Generate per-device metadata packages from the plants.yaml inventory.

plants.yaml is the source for non-secret per-device identity/display/tuning
metadata. Fixed display scales and recommendations live in plants.yaml, separate
from physical soil calibration. This tool emits one deterministic ESPHome package per
inventory key under examples/multi-device/packages/generated/.

Each generated package is identity-preserving: configured_name is set to the
already-effective <device_name>-<mac6> runtime name (the value stored as
mqtt_topic_prefix in the inventory) with name_add_mac_suffix false, so the
ESPHome node name, hostname and MQTT topic prefix stay byte-identical while the
MAC is no longer appended to the human friendly_name. The live secret-bearing
device YAML imports the matching package (plus wifi/use_address/secrets, which
must remain in the device file) during the coordinated infra-kl21 cutover.

Usage:
  python3 scripts/generate_device_metadata.py           # write/refresh packages
  python3 scripts/generate_device_metadata.py --check    # fail on any drift
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

if __package__:
    from .smartplant_gauge_contract import resolve_metrics, substitutions as scale_substitutions
    from .smartplant_screen_title import screen_title
else:
    from smartplant_gauge_contract import resolve_metrics, substitutions as scale_substitutions
    from smartplant_screen_title import screen_title

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "examples/multi-device/plants.yaml"
OUT_DIR = ROOT / "examples/multi-device/packages/generated"

HEADER = """\
# =============================================================================
# GENERATED FILE - DO NOT EDIT.
# Sources: examples/multi-device/plants.yaml (key: {key})
#          fixed display scales/recommendations and static illustration in that record
# Regenerate: python3 scripts/generate_device_metadata.py
# Drift check (CI): python3 scripts/generate_device_metadata.py --check
# -----------------------------------------------------------------------------
# Identity-preserving metadata. configured_name equals the already-effective
# <device_name>-<mac6> runtime name and name_add_mac_suffix is false, so the
# hostname / MQTT topic prefix stay byte-identical to the deployed device while
# the MAC is no longer appended to esphome.friendly_name (${{display_name}}).
# Naming guide: examples/multi-device/NAMING.md.
# device_name: stable technical key; configured_name: application/build name.
# display_name: full human device label, diagnostic comment and special pages.
# screen_title: normal-page title only; no HA/MQTT identity change.
# secondary_name: botanical/cultivar subtitle, also used in device_comment.
# Function-only entity names come from the core, not from these human labels.
# Edit the inventory and regenerate; keep naming overrides out of live YAML.
# Secrets and the wifi/use_address block stay in the live device YAML.
# =============================================================================
"""


def secondary_name(values: dict) -> str:
    """Botanical name if present, else the horticultural (cultivar) name.

    The immutable device_name slug carries no botanical authority (it is
    non-unique across the two Ceropegia); secondary_name is the descriptive
    label rendered under screen_title on the e-paper and in device_comment.
    """
    name = values.get("botanical_name") or values.get("horticultural_name")
    if not name:
        raise ValueError("no botanical_name or horticultural_name")
    return str(name)


def configured_name(key: str, values: dict) -> str:
    """The already-effective <device_name>-<mac6> runtime identity.

    mqtt_topic_prefix is authoritative (auto-derived for unique species,
    explicit for the duplicates). When the inventory also carries an explicit
    configured_name it MUST agree, or the inventory is internally inconsistent.
    """
    prefix = values["mqtt_topic_prefix"]
    explicit = values.get("configured_name")
    if explicit is not None and explicit != prefix:
        raise ValueError(
            f"{key}: configured_name '{explicit}' != mqtt_topic_prefix '{prefix}'"
        )
    return str(prefix)


def render(key: str, values: dict) -> str:
    cal = values["soil_calibration"]
    metrics = resolve_metrics(values["display"])
    illustration = Path(values["plant_illustration"])
    base = ROOT / "examples/multi-device"
    if illustration.is_absolute() or ".." in illustration.parts or not (base / illustration).is_file():
        raise ValueError(f"{key}: illustration must be an existing relative asset")
    fields = {
        "device_name": str(values["device_name"]),
        "configured_name": configured_name(key, values),
        "name_add_mac_suffix": "false",
        "display_name": str(values["display_name"]),
        "screen_title": screen_title(key, values),
        "secondary_name": secondary_name(values),
        "label_image": str(values["label_image"]),
        "plant_illustration": "https://raw.githubusercontent.com/flowcool/Smart_Plant/V2R1/"
                              f"examples/multi-device/{illustration.as_posix()}",
        # Preserve the existing fleet illustration placement and aspect-fit box.
        "illustration_x": "5",
        "illustration_y": "37",
        "illustration_width": "75",
        "illustration_height": "88",
        "timezone": str(values.get("timezone", "Europe/Paris")),
        "soil_v_wet": str(cal["wet_voltage"]),
        "soil_v_dry": str(cal["dry_voltage"]),
        **scale_substitutions(metrics),
    }
    for metric, prefix in (("moisture", "soil"), ("illuminance", "light"),
                           ("temperature", "temp"), ("humidity", "hum")):
        fields[f"{prefix}_recommended_min"], fields[f"{prefix}_recommended_max"] = map(str, metrics[metric]["band"])
    lines = [HEADER.format(key=key), "substitutions:"]
    for name, val in fields.items():
        # Double-quote every value; escape embedded quotes/backslashes.
        esc = val.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  {name}: "{esc}"')
    return "\n".join(lines) + "\n"


def load_inventory() -> dict:
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    plants = data.get("plants")
    if not plants:
        raise SystemExit(f"no 'plants' mapping in {INVENTORY}")
    return plants


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify on-disk packages match the inventory; exit 1 on drift",
    )
    args = ap.parse_args()

    plants = load_inventory()
    expected = {key: render(key, values) for key, values in plants.items()}

    if args.check:
        drift = []
        current = {p.name for p in OUT_DIR.glob("*.yaml")} if OUT_DIR.exists() else set()
        wanted = {f"{key}.yaml" for key in expected}
        for stale in sorted(current - wanted):
            drift.append(f"stale generated file not in inventory: {stale}")
        for key, content in expected.items():
            path = OUT_DIR / f"{key}.yaml"
            if not path.exists():
                drift.append(f"missing: {path.relative_to(ROOT)}")
            elif path.read_text(encoding="utf-8") != content:
                drift.append(f"drift: {path.relative_to(ROOT)}")
        if drift:
            print("generate_device_metadata --check FAILED:", file=sys.stderr)
            for d in drift:
                print(f"  {d}", file=sys.stderr)
            print("Run: python3 scripts/generate_device_metadata.py", file=sys.stderr)
            return 1
        print(f"OK: {len(expected)} generated packages match inventory and gauge inputs")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, content in expected.items():
        (OUT_DIR / f"{key}.yaml").write_text(content, encoding="utf-8")
    print(f"Wrote {len(expected)} packages to {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
