#!/usr/bin/env python3
"""Migrate production device YAMLs to generated SmartPlant metadata packages.

The transformation is deterministic and preserves the input line-ending style.
It removes duplicated naming/calibration substitutions, removes the redundant
top-level ``esphome.friendly_name`` override, replaces a literal ``ota_password``
substitution with ``!secret ota_password_<device>`` (the value is never read,
printed or stored; the operator adds the matching key to secrets.yaml), and adds
the device's matching generated metadata package before the shared core and
transport packages.

Run against an offline copy first:

    python3 scripts/migrate_live_device_metadata.py --directory PATH --check
    python3 scripts/migrate_live_device_metadata.py --directory PATH --write

``--check`` is also the post-migration drift gate. The tool never creates a
backup; live use requires a separately verified backup and rollback path.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "examples/multi-device/plants.yaml"
PACKAGE_PREFIX = (
    "github://flowcool/Smart_Plant/examples/multi-device/packages/generated"
)
PACKAGE_REF = "V2R1"

# These values belong to plants.yaml -> packages/generated/, never to a live
# device YAML. Obsolete fields are included so the migration removes them.
MANAGED_SUBSTITUTIONS = {
    "device_name",
    "configured_name",
    "name_add_mac_suffix",
    "display_name",
    "screen_title",
    "botanical_name",
    "horticultural_name",
    "secondary_name",
    "friendly_name",
    "device_comment",
    "label_image",
    "plant_illustration",
    "illustration_x",
    "illustration_y",
    "illustration_width",
    "illustration_height",
    "light_max",
    "temp_min",
    "temp_max",
    "hum_min",
    "hum_max",
    "soil_recommended_min",
    "soil_recommended_max",
    "light_recommended_min",
    "light_recommended_max",
    "temp_recommended_min",
    "temp_recommended_max",
    "hum_recommended_min",
    "hum_recommended_max",
    "timezone",
    "soil_v_wet",
    "soil_v_dry",
}

KEY_LINE = re.compile(r"^  ([A-Za-z0-9_]+):(?:\s|$)")
# A plant's OTA password must be a secret reference, never a literal in the device YAML.
OTA_LINE = re.compile(r"^  ota_password:(?:\s|$)")
OTA_REFERENCE = re.compile(r"^  ota_password:\s*!secret\s+\S+\s*(?:#.*)?$")


class TolerantLoader(yaml.SafeLoader):
    pass


def _keep_tag(loader, _tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


TolerantLoader.add_multi_constructor("!", _keep_tag)


def inventory_keys() -> list[str]:
    plants = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))["plants"]
    return list(plants)


def ota_secret_name(key: str) -> str:
    """Per-device secrets.yaml key; one key per device keeps each value independently rotatable."""
    return "ota_password_" + re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_")


def metadata_url(key: str) -> str:
    return f"{PACKAGE_PREFIX}/{key}.yaml@{PACKAGE_REF}"


def _block_end(lines: list[str], start: int) -> int:
    """Return the first line after a top-level YAML mapping block."""
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        index += 1
    return index


def transform(text: str, key: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    had_final_newline = text.endswith(("\n", "\r"))
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    saw_packages = False

    while index < len(lines):
        line = lines[index]
        if line == "esphome:":
            end = _block_end(lines, index)
            children = lines[index + 1:end]
            kept = [
                child for child in children
                if not re.match(r"^  friendly_name:(?:\s|$)", child)
            ]
            if any(child.strip() and not child.lstrip().startswith("#") for child in kept):
                output.append(line)
                output.extend(kept)
            index = end
            continue

        if line == "substitutions:":
            end = _block_end(lines, index)
            output.append(line)
            for child in lines[index + 1:end]:
                match = KEY_LINE.match(child)
                if match and match.group(1) in MANAGED_SUBSTITUTIONS:
                    continue
                if OTA_LINE.match(child) and not OTA_REFERENCE.match(child):
                    child = f"  ota_password: !secret {ota_secret_name(key)}"
                output.append(child)
            index = end
            continue

        if line == "packages:":
            end = _block_end(lines, index)
            saw_packages = True
            output.append(line)
            output.extend(
                child for child in lines[index + 1:end]
                if not re.match(r"^  metadata:(?:\s|$)", child)
            )
            # ESPHome merges packages in declaration order; the generated
            # device-specific values must come after the core defaults.
            output.append(f"  metadata: {metadata_url(key)}")
            index = end
            continue

        output.append(line)
        index += 1

    if not saw_packages:
        raise ValueError(f"{key}: missing top-level packages block")
    rendered = newline.join(output)
    return rendered + newline if had_final_newline else rendered


def validate(text: str, key: str) -> list[str]:
    errors: list[str] = []
    try:
        doc = yaml.load(text, Loader=TolerantLoader)
    except yaml.YAMLError as exc:
        return [f"invalid YAML: {exc}"]

    substitutions = doc.get("substitutions") or {}
    duplicated = sorted(MANAGED_SUBSTITUTIONS & substitutions.keys())
    if duplicated:
        errors.append(f"duplicated generated substitutions: {', '.join(duplicated)}")

    if any(OTA_LINE.match(line) and not OTA_REFERENCE.match(line) for line in text.splitlines()):
        errors.append("ota_password must be a !secret reference, not a literal")

    esphome = doc.get("esphome") or {}
    if "friendly_name" in esphome:
        errors.append("top-level esphome.friendly_name must come from core")

    packages = doc.get("packages") or {}
    if packages.get("metadata") != metadata_url(key):
        errors.append("missing or incorrect generated metadata package")
    if "core" not in packages or "transport" not in packages:
        errors.append("core and transport packages are required")
    if packages and list(packages)[-1] != "metadata":
        errors.append("metadata package must be last so it overrides core defaults")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    failures: list[str] = []
    changed = 0
    for key in inventory_keys():
        path = args.directory / f"{key}.yaml"
        if not path.exists():
            failures.append(f"{key}: missing {path}")
            continue
        original = path.read_bytes().decode("utf-8")
        rendered = transform(original, key)
        if args.write and rendered != original:
            path.write_bytes(rendered.encode("utf-8"))
            changed += 1
        candidate = rendered if args.write else original
        errors = validate(candidate, key)
        if errors:
            failures.extend(f"{key}: {error}" for error in errors)

    if failures:
        print("Live metadata validation FAILED:")
        for failure in failures:
            print(f"  {failure}")
        if args.check:
            print("Run --write only on a backed-up, offline copy first.")
        return 1

    if args.write:
        print(
            f"OK: migrated {changed}; validated {len(inventory_keys())} "
            "live device YAMLs"
        )
    else:
        print(f"OK: validated {len(inventory_keys())} live device YAMLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
