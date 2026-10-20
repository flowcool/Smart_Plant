"""Shared e-paper geometry and snapshot-derived display scales.

The snapshot's by_device_mac6.thresholds mapping is the accepted recommendation
source. number_entity_states_raw is historical evidence, not rendering input.
"""
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "examples/multi-device/label_maker"
CONTRACT = yaml.safe_load((INPUTS / "gauge-contract.yaml").read_text(encoding="utf-8"))
SNAPSHOT = INPUTS / "ha-thresholds-snapshot.json"


def full_scale(metric, recommended_min, recommended_max):
    if not (math.isfinite(recommended_min) and math.isfinite(recommended_max)
            and recommended_min <= recommended_max):
        raise ValueError(f"invalid recommendation for {metric}")
    settings = CONTRACT["metrics"][metric]
    if "range" in settings:
        minimum, maximum = settings["range"]
    else:
        step = settings["maximum_step"]
        minimum = settings["minimum"]
        maximum = max(step, math.ceil(recommended_max / step) * step)
    if not minimum <= recommended_min <= recommended_max <= maximum or minimum >= maximum:
        raise ValueError(f"recommendation outside full scale for {metric}")
    return [minimum, maximum]


def angle(value, scale):
    """Clockwise screen angle in radians, from +x; clamp only the pointer."""
    minimum, maximum = scale
    sweep = math.radians(CONTRACT["angle_degrees"])
    start = math.pi / 2 + (2 * math.pi - sweep) / 2
    return start + (min(max(value, minimum), maximum) - minimum) / (maximum - minimum) * sweep


def load_thresholds(snapshot=SNAPSHOT):
    return json.loads(Path(snapshot).read_text(encoding="utf-8"))["by_device_mac6"]


def device_scales(key, snapshot=None):
    snapshot = load_thresholds() if snapshot is None else snapshot
    thresholds = snapshot[key.rsplit("-", 1)[-1]]["thresholds"]
    return {metric: full_scale(metric, thresholds[metric]["min"], thresholds[metric]["max"])
            for metric in CONTRACT["metrics"]}
