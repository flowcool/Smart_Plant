#!/usr/bin/env python3
"""kl21.1 — join the SmartPlant AS-IS HA state with the deterministic TO-BE to
produce the validated 96-row entity migration map.

This tool is tracked; its inputs and outputs are NOT — they carry full-MAC
unique_ids and HA entity_ids and live in the gitignored tmp/naming-migration/
workspace, off the public fork.

Inputs:
  - examples/multi-device/plants.yaml              (tracked: node identity mqtt_topic_prefix)
  - tmp/naming-migration/ha-registry-asis.json     (gitignored, kl21.3: old entity_id/unique_id + rows)
  - tmp/naming-migration/ha-discovery-topics-asis.txt (gitignored, kl21.1 MQTT scan: old discovery topics)
Outputs (gitignored):
  - tmp/naming-migration/entity-mapping-96.{json,csv}

TO-BE rules (source-verified against esphome 2026.7.4):
  new_unique_id      = <fullmac>-<component>-<%08x fnv1(function label)>
  new payload obj_id = <node-dashed>_<function_snake>        (object_id_generator=device_name)
  new_entity_id      = <domain>.<node_underscored>_<function_snake>
  new_discovery_topic= homeassistant/<component>/<node>/<function_snake>/config

Hard validation: exactly 96 rows; 96 unique values for each of old/new
entity_id and unique_id; every entity paired to exactly one discovery topic;
every (mac6, component, function) unique. Exit non-zero on any violation.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WORK = REPO / "tmp/naming-migration"
PLANTS = REPO / "examples/multi-device/plants.yaml"
ASIS = WORK / "ha-registry-asis.json"
TOPICS = WORK / "ha-discovery-topics-asis.txt"
OUT_JSON = WORK / "entity-mapping-96.json"
OUT_CSV = WORK / "entity-mapping-96.csv"

# (entity name label, esphome object_id snake, mqtt component_type)
FUNCTIONS = [
    ("Battery", "battery", "sensor"),
    ("Temperature", "temperature", "sensor"),
    ("Air Humidity", "air_humidity", "sensor"),
    ("Ambient light", "ambient_light", "sensor"),
    ("Soil Moisture", "soil_moisture", "sensor"),
    ("ESPHome Version", "esphome_version", "sensor"),
    ("Maintenance Status", "maintenance_status", "sensor"),
    ("Storage Mode Status", "storage_mode_status", "sensor"),
    ("Maintenance", "maintenance", "switch"),
    ("Storage Mode", "storage_mode", "switch"),
    ("Pull OTA", "pull_ota", "switch"),
    ("Firmware pull update", "firmware_pull_update", "update"),
]
LABELS = {f[0]: f for f in FUNCTIONS}

FNV1_OFFSET_BASIS = 2166136261
FNV1_PRIME = 16777619
_MASK = 0xFFFFFFFF


def fnv1_hex(name: str) -> str:
    h = FNV1_OFFSET_BASIS
    for b in name.encode("utf-8"):
        h = (h * FNV1_PRIME) & _MASK
        h ^= b
        h &= _MASK
    return f"{h:08x}"


def longest_suffix_match(text: str, candidates, sep: str) -> str | None:
    """Return the candidate that is the longest sep-delimited suffix of text."""
    best = None
    for cand in candidates:
        if text == cand or text.endswith(sep + cand):
            if best is None or len(cand) > len(best):
                best = cand
    return best


def target_fields(
    fullmac: str,
    component: str,
    node: str,
    function_label: str,
    function_snake: str,
    domain: str,
) -> dict[str, str]:
    """Compute the distinct MQTT discovery and Home Assistant target fields.

    ESPHome's ``device_name`` object-id generator prefixes only the ``obj_id``
    value inside the discovery payload. The discovery topic itself continues
    to use the entity's function-only default object ID as its final segment.
    Home Assistant then slugifies the dashed payload object ID for entity_id.
    """
    payload_object_id = f"{node}_{function_snake}"
    entity_object_id = f"{node.replace('-', '_')}_{function_snake}"
    return {
        "new_discovery_topic": (
            f"homeassistant/{component}/{node}/{function_snake}/config"
        ),
        "new_object_id": payload_object_id,
        "new_entity_id": f"{domain}.{entity_object_id}",
        "new_unique_id": (
            f"{fullmac}-{component}-{fnv1_hex(function_label)}"
        ),
    }


def fail(msg: str):
    print(f"VALIDATION FAILED: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    plants = yaml.safe_load(PLANTS.read_text(encoding="utf-8"))["plants"]
    # mac6 -> node (mqtt_topic_prefix, dash form)
    node_by_mac6 = {}
    for key, v in plants.items():
        mac6 = v["mqtt_topic_prefix"].split("-")[-1].lower()
        node_by_mac6[mac6] = v["mqtt_topic_prefix"]

    asis = json.loads(ASIS.read_text(encoding="utf-8"))
    entities = asis["entities"]

    # --- index discovery topics by (mac6, component, function_snake) ----------
    topics = [t.strip() for t in TOPICS.read_text(encoding="utf-8").splitlines() if t.strip()]
    snakes = [f[1] for f in FUNCTIONS]
    topic_by_key = {}
    for t in topics:
        parts = t.split("/")
        # homeassistant/<component>/<node>/<object_id>/config
        if len(parts) != 5 or parts[0] != "homeassistant" or parts[-1] != "config":
            fail(f"unexpected discovery topic shape: {t}")
        component, node, object_id = parts[1], parts[2], parts[3]
        mac6 = node.split("-")[-1].lower()
        fn_snake = longest_suffix_match(object_id, snakes, "_")
        if fn_snake is None:
            fail(f"no function snake matched object_id {object_id!r} ({t})")
        key = (mac6, component, fn_snake)
        if key in topic_by_key:
            fail(f"duplicate discovery topic for {key}: {t} vs {topic_by_key[key]}")
        topic_by_key[key] = t

    # --- build rows -----------------------------------------------------------
    rows = []
    seen_triples = set()
    for e in entities:
        old_uid = e["unique_id"]
        fullmac, component = old_uid.split("-")[0], e["component_type"]
        mac6 = e["mac6"]
        label = longest_suffix_match(e["original_name"], LABELS.keys(), " ")
        if label is None:
            fail(f"no function label matched original_name {e['original_name']!r}")
        fn_label, fn_snake, fn_component = LABELS[label]
        if fn_component != component:
            fail(f"component mismatch for {label}: registry={component} expected={fn_component}")
        triple = (mac6, component, fn_snake)
        if triple in seen_triples:
            fail(f"duplicate (mac6, component, function): {triple}")
        seen_triples.add(triple)

        node = node_by_mac6.get(mac6)
        if node is None:
            fail(f"mac6 {mac6} not found in plants.yaml")
        domain = e["entity_id"].split(".")[0]
        target = target_fields(
            fullmac, component, node, fn_label, fn_snake, domain
        )
        old_topic = topic_by_key.get(triple)
        if old_topic is None:
            fail(f"no discovery topic for entity {e['entity_id']} ({triple})")

        rows.append({
            "inventory_key": f"{node}",
            "device_id": e["device_id"],
            "component_type": component,
            "function": fn_label,
            "old_discovery_topic": old_topic,
            "old_entity_id": e["entity_id"],
            "old_unique_id": old_uid,
            **target,
        })

    # --- validation -----------------------------------------------------------
    if len(rows) != 96:
        fail(f"expected 96 rows, got {len(rows)}")
    for col in (
        "old_discovery_topic", "old_entity_id", "old_unique_id",
        "new_discovery_topic", "new_object_id", "new_entity_id", "new_unique_id",
    ):
        vals = [r[col] for r in rows]
        if len(set(vals)) != 96:
            dup = [v for v in vals if vals.count(v) > 1]
            fail(f"{col} not 96 unique (dups: {sorted(set(dup))[:5]})")
    used_topics = {r["old_discovery_topic"] for r in rows}
    if len(used_topics) != 96 or used_topics != set(topics):
        fail(f"discovery topic coverage mismatch: matched {len(used_topics)} of {len(set(topics))}")

    rows.sort(key=lambda r: (r["inventory_key"], r["component_type"], r["function"]))
    OUT_JSON.write_text(json.dumps(
        {"manifest": {"rows": len(rows), "source_asis": ASIS.name,
                      "ha_version": asis["manifest"]["ha_version"],
                      "asis_extracted_at": asis["manifest"]["extracted_at_utc"],
                      "discovery_topic": "homeassistant/<component>/<node>/<function_snake>/config",
                      "payload_object_id": "<node-dashed>_<function_snake>",
                      "fnv1": "FNV-1 32-bit basis=2166136261 prime=16777619 %08x over entity name"},
         "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"OK: 96 rows validated -> {OUT_JSON.name}, {OUT_CSV.name}")
    print("  unique old/new topic, object_id, entity_id, unique_id: all 96")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
