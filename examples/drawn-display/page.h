#pragma once

#include <cmath>
#include <initializer_list>

// Generic offline candidate. No inventory, transport or Home Assistant access.
namespace smart_plant_page {
constexpr float kPi = 3.141592653589793f;
constexpr float kSweep = 4.71238898038469f;
constexpr float kStart = kPi / 2 + (2 * kPi - kSweep) / 2;

struct Reading {
  float value;
  bool present;
  bool valid() const { return present && std::isfinite(value); }
};

struct Gauge {
  float minimum, maximum;             // Display scale, not calibration.
  float recommended_min, recommended_max;
  int x, y;                           // Legacy top-left, radius = 22.
  const char *format;
  const char *icon;
  bool valid() const {
    return std::isfinite(minimum) && std::isfinite(maximum) &&
           std::isfinite(recommended_min) && std::isfinite(recommended_max) &&
           minimum < maximum && std::isfinite(maximum - minimum) && minimum <= recommended_min &&
           recommended_min <= recommended_max && recommended_max <= maximum;
  }
  float angle(float value) const {
    const float clamped = std::fmin(maximum, std::fmax(minimum, value));
    return kStart + (clamped - minimum) / (maximum - minimum) * kSweep;
  }
};

// The legacy artwork fills kStart -> midpoint of the recommendation. It does
// not fill recommended_min -> recommended_max. Preserve that visual contract.
// Pixel centres replace Cairo antialiasing; all distances remain in pixels.
template<class Display, class Color>
void ring(Display &it, const Gauge &g, Color fg) {
  const float endpoint = g.angle(g.recommended_min / 2 + g.recommended_max / 2);
  for (int y = -23; y <= 22; ++y) {
    for (int x = -23; x <= 22; ++x) {
      const float dx = x + 0.5f, dy = y + 0.5f;
      const float squared = dx * dx + dy * dy;
      if (squared < 16.5f * 16.5f || squared > 22.5f * 22.5f) continue;
      float angle = std::atan2(dy, dx);
      if (angle < kStart) angle += 2 * kPi;
      const bool in_sweep = angle <= kStart + kSweep;
      const bool fill = squared >= 17 * 17 && squared <= 22 * 22 && angle <= endpoint;
      const bool outline = squared <= 17.5f * 17.5f || squared >= 21.5f * 21.5f;
      if (in_sweep && (fill || outline)) it.draw_pixel_at(g.x + 22 + x, g.y + 22 + y, fg);
    }
  }
  // Radial end caps of the same five-pixel annulus.
  for (float a : {kStart, kStart + kSweep}) {
    it.line(static_cast<int>(std::round(g.x + 22 + 17 * std::cos(a))),
            static_cast<int>(std::round(g.y + 22 + 17 * std::sin(a))),
            static_cast<int>(std::round(g.x + 22 + 22 * std::cos(a))),
            static_cast<int>(std::round(g.y + 22 + 22 * std::sin(a))), fg);
  }
}

template<class Display, class Font, class Color, class Align>
void gauge(Display &it, const Gauge &g, Reading reading, Font *values, Font *icons,
           Color fg, Align centre) {
  if (g.valid()) ring(it, g, fg);
  it.print(g.x + 22, g.y + 11, icons, fg, centre, g.icon);
  if (!g.valid() || !reading.valid()) {
    it.print(g.x + 22, g.y + static_cast<int>(1.7 * 22), values, fg, centre, "--");
    return;
  }
  // Preserve the existing float/truncation geometry and the raw numeric label.
  const float a = g.angle(reading.value);
  const int x0 = static_cast<int>(g.x + 22 + 22 * ::cos(a));
  const int y0 = static_cast<int>(g.y + 22 + 22 * ::sin(a));
  const int x1 = static_cast<int>(g.x + 22 + 29 * ::cos(a + 0.1));
  const int y1 = static_cast<int>(g.y + 22 + 29 * ::sin(a + 0.1));
  const int x2 = static_cast<int>(g.x + 22 + 29 * ::cos(a - 0.1));
  const int y2 = static_cast<int>(g.y + 22 + 29 * ::sin(a - 0.1));
  it.line(x0, y0, x1, y1, fg);
  it.line(x1, y1, x2, y2, fg);
  it.line(x2, y2, x0, y0, fg);
  it.printf(g.x + 22, g.y + static_cast<int>(1.7 * 22), values, fg, centre, g.format, reading.value);
}
}  // namespace smart_plant_page
