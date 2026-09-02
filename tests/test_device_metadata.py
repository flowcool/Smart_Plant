"""Naming-decoupling regression suite (infra-zdxz.2).

Proves the three-layer naming model on the repository packages and the
generated per-device metadata:

  * technical identity (configured_name / MQTT prefix) is preserved byte-for-byte
    and is independent of the human display name;
  * every HA-exposed entity name is function-only, so no display/identity field
    leaks into an entity's MQTT unique_id;
  * the 12 function-only names yield collision-free MQTT unique_ids
    (fnv1_hash of the entity name, source-verified against ESPHome 2026.7.4);
  * changing display_name changes only human-display outputs, never identity.

Run: python3 -m unittest tests.test_device_metadata  (stdlib only).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "examples/multi-device/packages"
CORE = PKG / "smart_plant_core.yaml"
PROFILE_MQTT = PKG / "smart_plant_profile_mqtt.yaml"
GENERATED = PKG / "generated"

# --- load the generator module by path (no package install) -----------------
_spec = importlib.util.spec_from_file_location(
    "gen_meta", ROOT / "scripts/generate_device_metadata.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

# The 12 HA-exposed entity names (function-only) + 2 internal ones.
EXPOSED_NAMES = {
    "Battery", "Temperature", "Air Humidity", "Ambient light", "Soil Moisture",
    "ESPHome Version", "Maintenance", "Storage Mode", "Pull OTA",
    "Maintenance Status", "Storage Mode Status", "Firmware pull update",
}
INTERNAL_NAMES = {"Battery voltage", "Actual gain"}
ENTITY_SECTIONS = ("sensor", "text_sensor", "switch", "update", "binary_sensor")


# --- tolerant YAML loader: ESPHome tags (!lambda, !secret) become scalars ----
class _Tolerant(yaml.SafeLoader):
    pass


def _keep(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_Tolerant.add_multi_constructor("!", _keep)
_Tolerant.add_multi_constructor("", _keep)


def load_pkg(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Tolerant)


def load_text(text: str) -> dict:
    return yaml.load(text, Loader=_Tolerant)


def collect_names(doc: dict) -> list[str]:
    """All string values under a key named 'name' within entity sections."""
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "name" and isinstance(v, str):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for section in ENTITY_SECTIONS:
        if section in doc:
            walk(doc[section])
    return found


def all_entity_names() -> list[str]:
    return collect_names(load_pkg(CORE)) + collect_names(load_pkg(PROFILE_MQTT))


# --- FNV-1 32-bit, exactly as esphome/core/helpers.cpp @2026.7.4 -------------
# uint32_t hash = 2166136261; for each char: hash *= 16777619; hash ^= c;
FNV1_OFFSET_BASIS = 2166136261
FNV1_PRIME = 16777619
_MASK = 0xFFFFFFFF


def fnv1_hex(name: str) -> str:
    h = FNV1_OFFSET_BASIS
    for byte in name.encode("utf-8"):
        h = (h * FNV1_PRIME) & _MASK
        h ^= byte
        h &= _MASK
    return f"{h:08x}"


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.plants = gen.load_inventory()

    def test_generator_check_no_drift(self):
        """Committed generated packages match the inventory exactly."""
        for key, values in self.plants.items():
            path = GENERATED / f"{key}.yaml"
            self.assertTrue(path.exists(), f"missing generated package for {key}")
            self.assertEqual(
                path.read_text(encoding="utf-8"), gen.render(key, values),
                f"{key}.yaml drifted; run scripts/generate_device_metadata.py",
            )
        on_disk = {p.stem for p in GENERATED.glob("*.yaml")}
        self.assertEqual(on_disk, set(self.plants), "stale/missing generated files")

    def test_configured_name_equals_effective_prefix(self):
        """Identity-preserving: configured_name == already-effective MQTT prefix."""
        for key, values in self.plants.items():
            sub = load_pkg(GENERATED / f"{key}.yaml")["substitutions"]
            self.assertEqual(sub["configured_name"], values["mqtt_topic_prefix"])
            if values.get("configured_name") is not None:
                self.assertEqual(sub["configured_name"], values["configured_name"])

    def test_name_add_mac_suffix_false_on_all(self):
        for key in self.plants:
            sub = load_pkg(GENERATED / f"{key}.yaml")["substitutions"]
            self.assertEqual(sub["name_add_mac_suffix"], "false")

    def test_secondary_name_prefers_botanical_name(self):
        pep = self.plants["peperomia-tetraphylla-54a940"]
        sub = load_pkg(GENERATED / "peperomia-tetraphylla-54a940.yaml")["substitutions"]
        self.assertEqual(sub["secondary_name"], pep["botanical_name"])

    def test_secondary_name_falls_back_to_horticultural(self):
        pep = dict(self.plants["peperomia-tetraphylla-54a940"])
        pep["botanical_name"] = None
        sub = load_text(gen.render("peperomia-tetraphylla-54a940", pep))["substitutions"]
        self.assertEqual(sub["secondary_name"], pep["horticultural_name"])

    def test_display_rename_changes_only_human_outputs(self):
        key = "cyperus-papyrus-54a9b2"
        base = dict(self.plants[key])
        renamed = dict(base, display_name="Papyrus du Nil (renamed)")
        a = load_text(gen.render(key, base))["substitutions"]
        b = load_text(gen.render(key, renamed))["substitutions"]
        self.assertNotEqual(a["display_name"], b["display_name"])
        for field in ("device_name", "configured_name", "name_add_mac_suffix",
                      "secondary_name", "label_image", "timezone",
                      "soil_v_wet", "soil_v_dry"):
            self.assertEqual(a[field], b[field], f"{field} changed on a display rename")


class PackageNamingTests(unittest.TestCase):
    def test_no_friendly_name_substitution_remains(self):
        for path in (CORE, PROFILE_MQTT):
            self.assertNotIn("${friendly_name}", path.read_text(encoding="utf-8"))

    def test_esphome_friendly_name_derives_from_display_name(self):
        self.assertEqual(load_pkg(CORE)["esphome"]["friendly_name"], "${display_name}")

    def test_normal_page_uses_generated_secondary_name(self):
        text = CORE.read_text(encoding="utf-8")
        self.assertIn('"${secondary_name}"', text)
        self.assertNotIn("${botanical_name}", text)
        for key in gen.load_inventory():
            sub = load_pkg(GENERATED / f"{key}.yaml")["substitutions"]
            self.assertTrue(sub["secondary_name"], key)

    def test_object_id_generator_set(self):
        mqtt = load_pkg(PROFILE_MQTT)["mqtt"]
        self.assertEqual(mqtt["discovery_unique_id_generator"], "mac")
        self.assertEqual(mqtt["discovery_object_id_generator"], "device_name")

    def test_exposed_entity_names_are_function_only(self):
        names = all_entity_names()
        self.assertEqual(set(names), EXPOSED_NAMES | INTERNAL_NAMES)
        for n in names:
            self.assertNotIn("$", n, f"entity name interpolates a substitution: {n!r}")

    def test_unique_ids_collision_free(self):
        """fnv1_hash(entity name) distinct for every exposed function name, so
        <mac>-<component>-<fnv1(name)> cannot collide within a device."""
        hashes = {name: fnv1_hex(name) for name in EXPOSED_NAMES}
        self.assertEqual(len(set(hashes.values())), len(EXPOSED_NAMES),
                         f"fnv1 collision among function names: {hashes}")


if __name__ == "__main__":
    unittest.main()
