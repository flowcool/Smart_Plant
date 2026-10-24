"""Execute candidate C++ and, when requested, the real ESPHome host renderer.

DRAWN_DISPLAY_HOST=/absolute/path/to/program enables the exact ESPHome tests.
The host executable has no broker, Wi-Fi, HA or panel transport.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image, ImageChops
from PIL.ImageFilter import MaxFilter
import cairo
import yaml
from scripts.smartplant_gauge_contract import angle
import test_display_gauge as legacy

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "examples/drawn-display/page.h"

STUB = r'''
#include <array>
#include <iostream>
#include <iomanip>
#include <string>
#include <vector>
#include <cstdarg>
#include <cstdio>
#include "HEADER"
struct Display {
  std::string text;
  std::vector<std::array<int,4>> lines;
  void draw_pixel_at(int,int,int) {}
  void line(int x,int y,int xx,int yy,int) { lines.push_back({x,y,xx,yy}); }
  void print(int,int,int*,int,int,const char *str) { text=str; }
  void printf(int,int,int*,int,int,const char *fmt,...) {
    char buffer[256]; va_list args; va_start(args,fmt);
    vsnprintf(buffer,sizeof(buffer),fmt,args); va_end(args); text=buffer;
  }
  void start_clipping(int,int,int,int) {}
  void end_clipping() {}
};
int main(int argc,char **argv) {
  if(argc!=9) return 2;
  using namespace smart_plant_page;
  Gauge g{std::stof(argv[3]),std::stof(argv[4]),std::stof(argv[5]),std::stof(argv[6]),80,50,argv[7],"icon"};
  Reading r{std::stof(argv[1]),std::string(argv[2])=="1"};
  Display it; int font=0;
  gauge(it,g,r,&font,&font,1,0);
  std::cout << it.text << '\n';
  if(g.valid() && r.valid()) {
    std::cerr << std::setprecision(10) << g.angle(r.value);
    for(auto line=it.lines.end()-3; line!=it.lines.end(); ++line) {
      for(int v:*line) std::cout << v << ' ';
      std::cout << '\n';
    }
  }
}
'''


class DrawnGaugeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="smartplant-drawn-")
        cls.addClassCleanup(cls.temp.cleanup)
        path = Path(cls.temp.name)
        source = path / "gauge.cpp"
        source.write_text(STUB.replace("HEADER", str(HEADER)))
        cls.executable = path / "gauge"
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=undefined,float-cast-overflow", "-fno-sanitize-recover=all",
                        str(source), "-o", str(cls.executable)], check=True, capture_output=True)
        # Compile the existing needle unchanged, as an independent reference.
        cls.old = type("LegacyRecorder", (), {"addClassCleanup": cls.addClassCleanup})
        legacy.DisplayGaugeTests.setUpClass.__func__(cls.old)

    def run_gauge(self, value, present=True, scale=(0, 100), band=(20, 60), fmt="%.0f%%"):
        result = subprocess.run([str(self.executable), str(value), str(int(present)),
                                 *map(str, scale), *map(str, band), fmt, "unused"],
                                check=True, capture_output=True, text=True)
        output = result.stdout.splitlines()
        return output[0], [tuple(map(int, line.split())) for line in output[1:]], result.stderr

    def test_valid_values_and_boundaries_preserve_legacy_needles_and_raw_labels(self):
        for scale, band, fmt in [((0, 100), (20, 60), "%.0f%%"),
                                 ((0, 3775), (500, 2500), "%.0flx"),
                                 ((-10, 50), (15, 30), "%.0f°C"),
                                 ((20, 80), (30, 70), "%.0f%%")]:
            for value in [scale[0] - 100, scale[0], band[0], sum(band)/2,
                          band[1], scale[1], scale[1] + 100]:
                with self.subTest(scale=scale, value=value):
                    text, lines, _ = self.run_gauge(value, scale=scale, band=band, fmt=fmt)
                    old = subprocess.run([str(self.old.executable), str(value), "1",
                                          *map(str, scale), fmt, "80", "50"],
                                         check=True, capture_output=True, text=True).stdout.splitlines()
                    self.assertEqual(text, old[0])
                    self.assertEqual(lines, [tuple(map(int, line.split())) for line in old[1:]])

    def test_invalid_or_absent_readings_have_no_needle(self):
        for value, present in [(40, False), ("nan", True), ("inf", True), ("-inf", True)]:
            with self.subTest(value=value, present=present):
                self.assertEqual(self.run_gauge(value, present)[:2], ("--", []))

    def test_invalid_yaml_ranges_fail_closed(self):
        for scale, band in [((0, 0), (0, 0)), ((100, 0), (20, 60)),
                            ((0, 100), (-1, 60)), ((0, 100), (20, 101)),
                            ((0, 100), (60, 20)), ((0, 100), ("nan", 60)),
                            ((0, "inf"), (20, 60)), (("-3e38", "3e38"), (20, 60))]:
            self.assertEqual(self.run_gauge(50, scale=scale, band=band)[:2], ("--", []))

    def test_zero_width_and_scale_edge_recommendations_keep_midpoint_semantics(self):
        for band in [(0, 0), (100, 100), (0, 100), (50, 50)]:
            midpoint = sum(band) / 2
            _, _, measured = self.run_gauge(midpoint, band=band)
            self.assertAlmostEqual(float(measured), angle(midpoint, [0, 100]), delta=1e-6)

    def test_extreme_finite_values_have_bounded_needles(self):
        for value, endpoint in [("3e38", 100), ("-3e38", 0)]:
            text, lines, _ = self.run_gauge(value)
            self.assertNotEqual(text, "--")
            self.assertEqual(lines, self.run_gauge(endpoint)[1])


@unittest.skipUnless(os.environ.get("DRAWN_DISPLAY_HOST"), "set DRAWN_DISPLAY_HOST to run exact ESPHome pixel tests")
class ESPHomePageTests(unittest.TestCase):
    def render(self, battery=70, values=(40, 1500, 22, 50), present=True, **environment):
        with tempfile.TemporaryDirectory(prefix="smartplant-host-") as temporary:
            path = Path(temporary)
            image = path / "page.pgm"
            pairs = [(battery, True)] + [(value, present) for value in values]
            env = dict(os.environ, ESPHOME_PREFDIR=str(path / "prefs"), SMART_PLANT_OUTPUT=str(image),
                       SMART_PLANT_VALUES=" ".join(f"{value} {int(state)}" for value, state in pairs),
                       **environment)
            result = subprocess.run([os.environ["DRAWN_DISPLAY_HOST"]], env=env, cwd=path,
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("PROOF us=", result.stdout)
            self.assertNotIn("Encountered character without representation", result.stdout + result.stderr)
            with Image.open(image) as bitmap:
                return bitmap.copy()

    def test_warning_page_is_pixel_inverse_outside_changed_battery_text(self):
        normal, warning = self.render(), self.render(battery=25)
        diff = ImageChops.difference(normal, ImageChops.invert(warning))
        self.assertIsNone(diff.crop((0, 18, 296, 128)).getbbox())
        self.assertIsNone(diff.crop((0, 0, 194, 18)).getbbox())

    def test_warning_threshold_is_strictly_below_fixed_yaml_value(self):
        self.assertEqual(self.render(battery=29.99).getpixel((295, 127)), 0)
        self.assertEqual(self.render(battery=30).getpixel((295, 127)), 255)

    def test_missing_nan_infinity_and_extremes_render_in_both_polarities(self):
        for battery in (25, 70, "nan", "inf", "-inf", "3e38", "-3e38"):
            for values, present in [(("nan", "inf", "-inf", 0), True),
                                    ((0, 0, 0, 0), False),
                                    ((-100, 10000, -15, 120), True),
                                    (("3e38", "-3e38", "3e38", "-3e38"), True)]:
                with self.subTest(battery=battery, values=values):
                    self.assertEqual(self.render(battery, values, present).size, (296, 128))

    def test_long_titles_expose_existing_overflow_without_implicit_relayout(self):
        empty = self.render(SMART_PLANT_TITLE="", SMART_PLANT_SUBTITLE="")
        long = self.render(SMART_PLANT_TITLE="W" * 100, SMART_PLANT_SUBTITLE="W" * 100)
        # This is an observed compatibility limit, not a layout acceptance claim.
        self.assertIsNotNone(ImageChops.difference(empty, long).crop((194, 0, 296, 37)).getbbox())
        for title in ("100% Pilea", "Prêle et cœurs"):
            candidate = self.render(SMART_PLANT_TITLE=title, SMART_PLANT_SUBTITLE="")
            diff = ImageChops.difference(empty, candidate)
            self.assertIsNone(diff.crop((194, 0, 296, 128)).getbbox())
            self.assertIsNone(diff.crop((0, 37, 296, 128)).getbbox())
            self.assertIsNotNone(diff.getbbox())

    def test_valid_clock_changes_only_clock_area(self):
        diff = ImageChops.difference(self.render(), self.render(SMART_PLANT_CLOCK_VALID="1"))
        self.assertIsNotNone(diff.crop((194, 18, 278, 37)).getbbox())
        self.assertIsNone(diff.crop((0, 37, 296, 128)).getbbox())

    def test_band_edges_zero_width_and_whole_scale_have_preserved_fill_meaning(self):
        def rings(band):
            return self.render(SMART_PLANT_RING_ONLY="1", SMART_PLANT_RECOMMENDATION=band)
        minimum, middle, maximum = rings("0 0"), rings("0.5 0.5"), rings("1 1")
        self.assertIsNone(ImageChops.difference(middle, rings("0 1")).getbbox())
        counts = [sum(p == 0 for p in image.getdata()) for image in (minimum, middle, maximum)]
        self.assertLess(counts[0], counts[1])
        self.assertLess(counts[1], counts[2])

    def test_ring_raster_preserves_legacy_geometry_with_one_pixel_edge_tolerance(self):
        from scripts import smartplant_label_maker as reference
        page = yaml.safe_load((ROOT / "examples/drawn-display/page.yaml").read_text())
        values = page["substitutions"]
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 296, 128)
        context = cairo.Context(surface)
        context.set_source_rgb(1, 1, 1)
        context.paint()
        for prefix, scale, position in [
            ("soil", [0, 100], [80, 50]),
            ("light", [0, float(values["light_max"])], [134, 70]),
            ("temp", [float(values["temp_min"]), float(values["temp_max"])], [188, 50]),
            ("hum", [float(values["hum_min"]), float(values["hum_max"])], [242, 70]),
        ]:
            reference.plot_parameter(context, {
                "abs_range": scale, "rel_range": [float(values[f"{prefix}_recommended_min"]),
                                                   float(values[f"{prefix}_recommended_max"])],
                "position": position, "radius": 22})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reference.png"
            surface.write_to_png(str(path))
            with Image.open(path) as image:
                expected = image.convert("L").point(lambda p: 255 if p >= 160 else 0)
        candidate = self.render(SMART_PLANT_RING_ONLY="1")
        # Cairo antialiasing and ESPHome binary pixels use different coverage.
        # Every ink pixel must be within one pixel of the other renderer's ink.
        actual_ink, expected_ink = ImageChops.invert(candidate), ImageChops.invert(expected)
        self.assertIsNone(ImageChops.subtract(actual_ink, expected_ink.filter(MaxFilter(3))).getbbox())
        self.assertIsNone(ImageChops.subtract(expected_ink, actual_ink.filter(MaxFilter(3))).getbbox())
        difference = ImageChops.difference(candidate, expected)
        self.assertLess(sum(bool(p) for p in difference.getdata()), 300)


if __name__ == "__main__":
    unittest.main()
