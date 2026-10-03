"""
Стиль субтитров: шрифт, размер, положение, цвета, обводка, тень, плашка.

Стиль — обычный dict (хранится в JSON). Стандартный стиль берётся из
настроек субтитров в админке, пользовательские — из шаблонов пользователя.
Все размеры задаются для кадра 1080x1920 и масштабируются под видео.
"""

import re
import struct
from pathlib import Path

from app.config import settings
from app.storage import SUBTITLE_COLORS, get_runtime


DEFAULT_FONT = "Arial"

# Шрифты, которые обычно есть в Windows. На другой ОС FFmpeg подставит
# похожий; загруженные в assets/fonts работают везде.
SYSTEM_FONTS = (
    "Arial",
    "Impact",
    "Verdana",
    "Tahoma",
    "Trebuchet MS",
    "Georgia",
    "Times New Roman",
    "Comic Sans MS",
    "Courier New",
)

FONT_EXTENSIONS = frozenset({".ttf", ".otf"})

# Ключ -> (минимум, максимум)
STYLE_LIMITS: dict[str, tuple[int, int]] = {
    "font_size": (30, 140),
    "bottom_offset_percent": (2, 90),
    "margin_percent": (0, 30),
    "outline": (0, 15),
    "max_line_length": (12, 50),
    "shadow": (0, 10),
}

STYLE_FLAGS = ("bold", "italic", "uppercase", "box")
STYLE_COLORS = ("text_color", "outline_color")

STYLE_DEFAULTS: dict = {
    "font": DEFAULT_FONT,
    "font_size": 68,
    "bottom_offset_percent": 15,
    "margin_percent": 8,
    "outline": 6,
    "max_line_length": 30,
    "shadow": 0,
    "text_color": "white",
    "outline_color": "pink",
    "bold": True,
    "italic": False,
    "uppercase": False,
    "box": False,
}

HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")


# ==========================================
# Нормализация
# ==========================================

def parse_hex_color(text: str) -> str | None:
    match = HEX_COLOR_PATTERN.match((text or "").strip())
    return f"#{match.group(1).upper()}" if match else None


def _valid_color(value) -> bool:
    return value in SUBTITLE_COLORS or (
        isinstance(value, str) and parse_hex_color(value) == value
    )


def normalize_style(style: dict | None) -> dict:
    result = dict(STYLE_DEFAULTS)

    for key, value in (style or {}).items():
        if key not in result:
            continue

        if key in STYLE_LIMITS:
            minimum, maximum = STYLE_LIMITS[key]

            try:
                result[key] = max(minimum, min(maximum, int(round(float(value)))))
            except (TypeError, ValueError):
                pass

        elif key in STYLE_FLAGS:
            result[key] = bool(value)

        elif key in STYLE_COLORS:
            if _valid_color(value):
                result[key] = value

        elif key == "font":
            # Запятая ломает строку стиля в ASS.
            font = str(value).replace(",", " ").strip()[:60]
            result[key] = font or DEFAULT_FONT

    return result


def default_style() -> dict:
    """
    Стандартный стиль — из настроек субтитров в админке.
    """

    runtime = get_runtime()

    return normalize_style(
        {
            "font_size": runtime["subtitle_font_size"],
            "bottom_offset_percent": runtime["subtitle_bottom_offset_percent"],
            "margin_percent": runtime["subtitle_margin_percent"],
            "outline": runtime["subtitle_outline"],
            "max_line_length": runtime["subtitle_max_line_length"],
            "text_color": runtime["subtitle_text_color"],
            "outline_color": runtime["subtitle_outline_color"],
        }
    )


# ==========================================
# Цвета
# ==========================================

def color_to_ass(value: str, alpha: int = 0) -> str:
    """
    Цвет из пресета или #RRGGBB → ASS &HAABBGGRR.
    """

    if value in SUBTITLE_COLORS:
        colour = SUBTITLE_COLORS[value][1]
        return f"&H{alpha:02X}{colour[4:]}"

    hex_value = (parse_hex_color(value) or "#FFFFFF")[1:]
    red, green, blue = hex_value[0:2], hex_value[2:4], hex_value[4:6]

    return f"&H{alpha:02X}{blue}{green}{red}"


def color_title(value: str) -> str:
    if value in SUBTITLE_COLORS:
        return SUBTITLE_COLORS[value][0]

    return value


# ==========================================
# Шрифты
# ==========================================

def read_font_family(font_file: Path) -> str | None:
    """
    Имя семейства из таблицы name файла TTF/OTF (или первого шрифта TTC).
    Именно по нему libass ищет шрифт.
    """

    try:
        data = font_file.read_bytes()

        offset = 0

        if data[:4] == b"ttcf":
            offset = struct.unpack(">I", data[12:16])[0]

        table_count = struct.unpack(">H", data[offset + 4:offset + 6])[0]
        name_offset = None

        for index in range(table_count):
            record = offset + 12 + 16 * index

            if data[record:record + 4] == b"name":
                name_offset = struct.unpack(">I", data[record + 8:record + 12])[0]
                break

        if name_offset is None:
            return None

        _, count, strings_offset = struct.unpack(
            ">HHH", data[name_offset:name_offset + 6]
        )

        candidates: list[tuple[int, str]] = []

        for index in range(count):
            record = name_offset + 6 + 12 * index
            platform, _, language, name_id, length, start = struct.unpack(
                ">HHHHHH", data[record:record + 12]
            )

            if name_id != 1:
                continue

            begin = name_offset + strings_offset + start
            raw = data[begin:begin + length]

            if platform in (0, 3):
                name = raw.decode("utf-16-be", errors="ignore")
                priority = 0 if language == 0x409 else 1
            elif platform == 1:
                name = raw.decode("mac_roman", errors="ignore")
                priority = 2
            else:
                continue

            name = name.replace(",", " ").strip()

            if name:
                candidates.append((priority, name))

    except (OSError, struct.error):
        return None

    return min(candidates)[1] if candidates else None


def uploaded_fonts() -> list[str]:
    directory = settings.fonts_dir

    if not directory.is_dir():
        return []

    families: list[str] = []

    for file in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if not file.is_file() or file.suffix.lower() not in FONT_EXTENSIONS:
            continue

        family = read_font_family(file)

        if family and family not in families:
            families.append(family)

    return families


def available_fonts() -> list[str]:
    """
    Сначала загруженные шрифты, затем стандартные системные.
    """

    fonts = uploaded_fonts()

    return fonts + [font for font in SYSTEM_FONTS if font not in fonts]


def fonts_dir_option() -> str:
    """
    Параметр fontsdir для фильтра ass (путь относительно корня проекта,
    FFmpeg запускается оттуда; без «:» из путей Windows).
    """

    if not settings.fonts_dir.is_dir():
        return ""

    relative = settings.fonts_dir.resolve().relative_to(
        settings.base_dir.resolve()
    ).as_posix()

    return f":fontsdir='{relative}'"
