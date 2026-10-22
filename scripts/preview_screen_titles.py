#!/usr/bin/env python3
"""Render the eight normal-page title previews without device access.

Usage: python3 scripts/preview_screen_titles.py
The preview uses the local Audiowide font. Firmware rasterization can differ.
Battery/time values are illustrative. Sensor values and live needles are omitted.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if __package__:
    from .generate_device_metadata import ROOT, load_inventory, secondary_name
    from .smartplant_screen_title import screen_title, title_font, title_width
else:
    from generate_device_metadata import ROOT, load_inventory, secondary_name
    from smartplant_screen_title import screen_title, title_font, title_width


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/screen-titles")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plants = load_inventory()
    sheet = Image.new("RGB", (640, 4 * 190), "#e7e7e7")
    labels = ImageDraw.Draw(sheet)
    for index, (key, values) in enumerate(plants.items()):
        title = screen_title(key, values)
        page = Image.open(ROOT / "examples/multi-device" / values["label_image"]).convert("RGB")
        draw = ImageDraw.Draw(page)
        draw.text((2, 0), title, font=title_font(), fill="black", anchor="lt")
        draw.text((2, 22), secondary_name(values), font=title_font(15), fill="black", anchor="lt")
        draw.text((278, 1), "100%", font=title_font(15), fill="black", anchor="rt")
        draw.rectangle((280, 5, 293, 14), outline="black")
        draw.text((278, 18), "12:34 22/10", font=title_font(15), fill="black", anchor="rt")
        page.save(args.output / f"{key}.png")
        x, y = 12 + index % 2 * 320, 12 + index // 2 * 190
        labels.text((x, y), key, font=ImageFont.load_default(), fill="black")
        sheet.paste(page, (x, y + 20))
        labels.text((x, y + 152), f"{len(title)} chars / {title_width(title)}px", fill="black")
        print(f"{key}: {title!r} ({len(title)} chars, {title_width(title)}px)")
    sheet.save(args.output / "fleet.png")
    print(f"Preview: {args.output / 'fleet.png'}")


if __name__ == "__main__":
    main()
