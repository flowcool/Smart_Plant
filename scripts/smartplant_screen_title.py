"""Offline validation for the fleet's normal-page e-paper title."""
from pathlib import Path

from PIL import ImageFont

FONT_PATH = Path(__file__).resolve().parents[1] / "examples/multi-device/label_maker/fonts/Audiowide-Regular.ttf"
FONT_SIZE = 20
MAX_CHARACTERS = 18
# Peperomia ‘Hope’ and Guirlande Cuisine are both 191 px in the offline checker.
MAX_WIDTH = 192


def title_font(size: int = FONT_SIZE):
    # BASIC disables optional shaping/kerning, as ESPHome draws glyphs in order.
    return ImageFont.truetype(str(FONT_PATH), size, layout_engine=ImageFont.Layout.BASIC)


def title_width(text: str) -> int:
    font = title_font()
    left, _, right, _ = font.getbbox(text)
    return max(right - left, round(font.getlength(text)))


def screen_title(key: str, values: dict) -> str:
    """Use an explicit screen-only title, or the full display name if it fits."""
    title = values.get("screen_title", values["display_name"])
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"{key}: screen_title must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 or char in "\u2028\u2029" for char in title):
        raise ValueError(f"{key}: screen_title must be one line without control characters")
    if any(char in title for char in ('"', "\\")):
        raise ValueError(f"{key}: screen_title must not contain double quotes or backslashes; use typographic quotes")
    if len(title) > MAX_CHARACTERS:
        raise ValueError(f"{key}: screen_title exceeds {MAX_CHARACTERS} characters; set a shorter screen_title")
    width = title_width(title)
    if width > MAX_WIDTH:
        raise ValueError(f"{key}: screen_title is {width}px, limit {MAX_WIDTH}px; set a shorter screen_title")
    return title
