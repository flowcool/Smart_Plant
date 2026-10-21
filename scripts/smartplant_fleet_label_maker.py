#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SmartPlant name-free e-paper label generator (infra-zdxz.3).

Regenerates the 296x128 `page_1_background` PNGs so that:
  - the plant NAME is NOT baked in (ESPHome renders display_name/secondary_name
    as dynamic text on the normal page); the background carries only the
    hand-drawn illustration + the four recommended-range gauge arcs;
  - the arcs are reproducible from the infra-kl21.4 HA threshold snapshot
    (rel_range = HA-authoritative thresholds), not from lost per-plant JSON.

Arc rendering derives from JGAguado/Label-maker Plants_labels.py. Its endpoint
angle is corrected to use the same start angle as the runtime needle.
Geometry and full scales come from label_maker/fleet-gauge-contract.yaml, which also
drives generated per-device firmware scales. The accepted HA snapshot remains
the recommendation source; its historical raw-entity appendix is not input.
"""
import math
import argparse
from pathlib import Path

import cairo

if __package__:
    from .smartplant_fleet_gauge_contract import CONTRACT, angle as gauge_angle, full_scale, load_thresholds
else:
    from smartplant_fleet_gauge_contract import CONTRACT, angle as gauge_angle, full_scale, load_thresholds

SIZE = tuple(CONTRACT["size"])
GAUGE_ANGLE_DEG = CONTRACT["angle_degrees"]
GAUGE_RADIUS = CONTRACT["radius"]
GAUGE_THICK = CONTRACT["arc_thickness"]
GAUGES = CONTRACT["metrics"]

INK = (0.0, 0.0, 0.0)  # single ink; panel is 1-bit BINARY, colour is cosmetic


# Arc renderer derived from JGAguado/Label-maker Plants_labels.py.
def draw_image(ctx, image, top, left, height, width, rot=0):
    image_surface = cairo.ImageSurface.create_from_png(image)
    img_height = image_surface.get_height()
    img_width = image_surface.get_width()
    width_ratio = float(width) / float(img_width)
    height_ratio = float(height) / float(img_height)
    scale_xy = min(height_ratio, width_ratio)
    ctx.save()
    ctx.rotate(rot * math.pi / 180)
    ctx.translate(left, top)
    ctx.scale(scale_xy, scale_xy)
    ctx.set_source_surface(image_surface)
    ctx.paint()
    ctx.restore()


def plot_parameter(ctx, parameter, thick=GAUGE_THICK):
    alpha = math.radians(GAUGE_ANGLE_DEG)
    beta = 2 * math.pi - alpha

    rel_range = parameter["rel_range"]
    abs_r = parameter["abs_range"]
    left = parameter["position"][0]
    top = parameter["position"][1]
    radius = parameter["radius"]

    if rel_range[0] < abs_r[0] or rel_range[1] > abs_r[1]:
        raise ValueError(f"rel_range {rel_range} not within abs_range {abs_r}")

    endpoint = gauge_angle(sum(rel_range) / 2, abs_r)

    # Icon (centred in the ring)
    size = radius
    draw_image(ctx, parameter["icon"],
               top + radius - size / 2, left + radius - size / 2, size, size)

    # Filled segment: gauge start -> midpoint of recommended band
    ctx.set_line_width(1)
    ctx.set_source_rgb(*INK)
    ctx.move_to(left + radius + (radius - thick) * math.cos(math.pi / 2 + beta / 2),
                top + radius + (radius - thick) * math.sin(math.pi / 2 + beta / 2))
    ctx.arc(left + radius, top + radius, radius, math.pi / 2 + beta / 2, endpoint)
    ctx.line_to(left + radius + radius * math.cos(endpoint),
                top + radius + radius * math.sin(endpoint))
    ctx.arc_negative(left + radius, top + radius, radius - thick, endpoint, math.pi / 2 + beta / 2)
    ctx.fill()
    ctx.stroke()

    # Full 270deg contour outline
    ctx.set_source_rgb(*INK)
    ctx.move_to(left + radius + (radius - thick) * math.cos(math.pi / 2 + beta / 2),
                top + radius + (radius - thick) * math.sin(math.pi / 2 + beta / 2))
    ctx.arc(left + radius, top + radius, radius, math.pi / 2 + beta / 2, math.pi / 2 - beta / 2)
    ctx.line_to(left + radius + radius * math.cos(math.pi / 2 - beta / 2),
                top + radius + radius * math.sin(math.pi / 2 - beta / 2))
    ctx.arc_negative(left + radius, top + radius, radius - thick, math.pi / 2 - beta / 2, math.pi / 2 + beta / 2)
    ctx.stroke()


# ---------------------------------------------------------------------------
def render_label(out_path, illustration, icons_dir, thresholds,
                 illo=(5, 37), illsize=(75, 88)):
    """Compose one name-free 296x128 background PNG."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, *SIZE)
    ctx = cairo.Context(surface)
    # White background (BINARY: off pixels show the panel's white)
    ctx.rectangle(0, 0, *SIZE)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()

    # Hand-drawn illustration, left region (below the dynamic name area)
    draw_image(ctx, str(illustration), illo[1], illo[0], illsize[1], illsize[0])

    # Four recommended-range arcs
    for metric, g in GAUGES.items():
        rmin = thresholds[metric]["min"]
        rmax = thresholds[metric]["max"]
        plot_parameter(ctx, {
            "rel_range": [rmin, rmax],
            "abs_range": full_scale(metric, rmin, rmax),
            "position": g["position"],
            "radius": GAUGE_RADIUS,
            "icon": str(Path(icons_dir) / g["icon"]),
        })

    surface.write_to_png(str(out_path))
    # Flatten cairo's antialiased RGB to a clean 1-bit image: the panel is a
    # 2.90inv2 BINARY e-paper, so grey edge pixels are noise. Done in code (not
    # by hand) to keep the output reproducible. Threshold 160 matches the
    # hand-quantised reference within 99% of pixels.
    from PIL import Image
    Image.open(out_path).convert("L").point(
        lambda p: 255 if p >= 160 else 0, mode="1").save(out_path)


def load_plants(plants_yaml):
    import yaml
    with open(plants_yaml) as f:
        return yaml.safe_load(f)["plants"]


def main():
    ap = argparse.ArgumentParser(description="SmartPlant name-free label generator")
    ap.add_argument("--snapshot", required=True, help="kl21.4 HA threshold snapshot JSON")
    ap.add_argument("--plants", required=True, help="plants.yaml identity registry")
    ap.add_argument("--illustrations", required=True, help="dir of <Botanical_name>.png illustrations")
    ap.add_argument("--icons", required=True, help="dir of gauge icon PNGs")
    ap.add_argument("--out", required=True, help="output dir for generated PNGs")
    args = ap.parse_args()

    snap = load_thresholds(args.snapshot)
    plants = load_plants(args.plants)
    illu_dir = Path(args.illustrations)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # index snapshot by mac6 suffix of the device key
    jobs = {}
    for key, p in plants.items():
        mac6 = key.rsplit("-", 1)[-1]
        if mac6 not in snap:
            raise SystemExit(f"no snapshot thresholds for {key} (mac6={mac6})")
        # Join illustration on the label_image stem, not botanical_name:
        # both derive from the same original baked PNG, whereas botanical_name
        # is null/cultivar-mismatched for some devices (e.g. Peperomia_Hope).
        stem = Path(p["label_image"]).name.replace("_label_page_1.png", "")
        illustration = illu_dir / f"{stem}.png"
        if not illustration.exists():
            raise SystemExit(f"missing illustration {illustration} for {key}")
        out_png = out / Path(p["label_image"]).name
        thresholds = snap[mac6]["thresholds"]
        signature = [(metric, thresholds[metric], full_scale(
            metric, thresholds[metric]["min"], thresholds[metric]["max"]))
            for metric in GAUGES]
        if out_png.name in jobs and jobs[out_png.name][0] != signature:
            raise SystemExit(f"conflicting thresholds/scales for shared image {out_png.name}")
        jobs[out_png.name] = (signature, illustration, thresholds)
        print(f"OK {key:32s} <- {stem:24s} -> {out_png.name}")

    # Validate all shared filenames before writing any output.
    for filename, (_, illustration, thresholds) in jobs.items():
        render_label(out / filename, illustration, args.icons, thresholds)
    print(f"\n{len(jobs)} unique labels for {len(plants)} devices generated in {out}")


if __name__ == "__main__":
    main()
