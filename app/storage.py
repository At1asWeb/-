"""
Простое JSON-хранилище:

- runtime-настройки, которые админ меняет прямо из бота;
- статистика обработок.
"""

import json
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings


_lock = threading.Lock()

RUNTIME_FILE = settings.data_dir / "runtime_settings.json"
STATS_FILE = settings.data_dir / "stats.json"
TEMPLATES_FILE = settings.data_dir / "subtitle_templates.json"

MAX_TEMPLATES_PER_USER = 10


# ==========================================
# Общие функции
# ==========================================

def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Не удалось прочитать {path.name}: {error}")
        return {}

    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


# ==========================================
# Runtime-настройки
# ==========================================

BANNER_FIT_MODES = ("fit", "crop", "stretch")

# Высота баннера меньше этого значения = «авто».
BANNER_HEIGHT_AUTO_BELOW = 5

# Ключ -> (минимум, максимум)
RUNTIME_LIMITS: dict[str, tuple[float, float]] = {
    "banner_width_percent": (10, 100),
    "banner_height_percent": (0, 60),
    "banner_top_offset_percent": (0, 80),
    "banner_opacity": (0.1, 1.0),
    "music_volume_percent": (1, 30),
    "subtitle_font_size": (30, 140),
    "subtitle_bottom_offset_percent": (2, 90),
    "subtitle_margin_percent": (0, 30),
    "subtitle_outline": (0, 15),
    "subtitle_max_line_length": (12, 50),
    "top_overlay_height_percent": (10, 70),
}

# Цвета субтитров: ключ -> (название, цвет ASS &HAABBGGRR).
SUBTITLE_COLORS: dict[str, tuple[str, str]] = {
    "white": ("белый", "&H00FFFFFF"),
    "yellow": ("жёлтый", "&H0000FFFF"),
    "black": ("чёрный", "&H00000000"),
    "pink": ("розово-фиолетовый", "&H00CC00FF"),
    "red": ("красный", "&H000000FF"),
    "green": ("зелёный", "&H0000CC00"),
    "blue": ("синий", "&H00FF6600"),
}

SUBTITLE_COLOR_KEYS = ("subtitle_text_color", "subtitle_outline_color")

TOP_OVERLAY_KEYS = ("top_overlay_height_percent",)

SUBTITLE_SETTING_KEYS = (
    "subtitle_font_size",
    "subtitle_bottom_offset_percent",
    "subtitle_margin_percent",
    "subtitle_outline",
    "subtitle_max_line_length",
    *SUBTITLE_COLOR_KEYS,
)


def _runtime_defaults() -> dict:
    average_volume = (
        settings.music_volume_min + settings.music_volume_max
    ) / 2

    return {
        "music_enabled": True,
        "music_volume_percent": round(average_volume * 100, 1) or 2.0,
        "banner_width_percent": settings.banner_width_percent,
        "banner_height_percent": settings.banner_height_percent,
        "banner_fit": settings.banner_fit,
        "banner_top_offset_percent": settings.banner_top_offset_percent,
        "banner_opacity": settings.banner_opacity,
        # Субтитры (значения — для кадра 1080x1920, масштабируются под видео).
        "subtitle_font_size": 68,
        "subtitle_bottom_offset_percent": 15,
        "subtitle_margin_percent": 8,
        "subtitle_outline": 6,
        "subtitle_max_line_length": 30,
        "subtitle_text_color": "white",
        "subtitle_outline_color": "pink",
        # Режим «видео сверху»: высота наложения, % от высоты кадра.
        "top_overlay_height_percent": 30,
    }


def _clamp(key: str, value):
    if key == "banner_fit":
        return value if value in BANNER_FIT_MODES else "fit"

    if key in SUBTITLE_COLOR_KEYS:
        return value if value in SUBTITLE_COLORS else _runtime_defaults()[key]

    if key not in RUNTIME_LIMITS:
        return value

    if key == "banner_height_percent" and value < BANNER_HEIGHT_AUTO_BELOW:
        return 0

    minimum, maximum = RUNTIME_LIMITS[key]
    value = max(minimum, min(maximum, value))

    if isinstance(minimum, int) and isinstance(maximum, int):
        return int(round(value))

    return round(float(value), 2)


def get_runtime() -> dict:
    with _lock:
        stored = _read_json(RUNTIME_FILE)

    result = _runtime_defaults()

    for key, value in stored.items():
        if key in result:
            result[key] = _clamp(key, value)

    return result


def update_runtime(**changes) -> dict:
    with _lock:
        stored = _read_json(RUNTIME_FILE)
        defaults = _runtime_defaults()

        for key, value in changes.items():
            if key not in defaults:
                raise KeyError(f"Неизвестная настройка: {key}")

            stored[key] = _clamp(key, value)

        _write_json(RUNTIME_FILE, stored)

    return get_runtime()


def reset_runtime(keys: tuple[str, ...] | None = None) -> dict:
    """
    Сбрасывает все настройки или только перечисленные ключи.
    """

    with _lock:
        if keys is None:
            if RUNTIME_FILE.exists():
                RUNTIME_FILE.unlink()
        else:
            stored = _read_json(RUNTIME_FILE)

            for key in keys:
                stored.pop(key, None)

            _write_json(RUNTIME_FILE, stored)

    return get_runtime()


# ==========================================
# Статистика
# ==========================================

def _empty_stats() -> dict:
    return {
        "total": 0,
        "success": 0,
        "failed": 0,
        "by_mode": {},
        "with_subtitles": 0,
        "with_banner": 0,
        "processing_seconds": 0.0,
        "users": [],
        "by_day": {},
        "last_run": None,
        "last_error": None,
    }


def record_processing(
    user_id: int,
    mode: str,
    subtitles: bool,
    banner: bool,
    success: bool,
    seconds: float,
    error: str | None = None,
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")

    with _lock:
        stats = _empty_stats()
        stats.update(_read_json(STATS_FILE))

        stats["total"] += 1

        if success:
            stats["success"] += 1
            stats["by_mode"][mode] = stats["by_mode"].get(mode, 0) + 1
            stats["processing_seconds"] += seconds

            if subtitles:
                stats["with_subtitles"] += 1

            if banner:
                stats["with_banner"] += 1

            stats["by_day"][today] = stats["by_day"].get(today, 0) + 1

        else:
            stats["failed"] += 1
            stats["last_error"] = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "text": (error or "")[:300],
            }

        if user_id not in stats["users"]:
            stats["users"].append(user_id)

        stats["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # Храним только последние 30 дней.
        border = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        stats["by_day"] = {
            day: count
            for day, count in stats["by_day"].items()
            if day >= border
        }

        _write_json(STATS_FILE, stats)


def get_stats() -> dict:
    with _lock:
        stats = _empty_stats()
        stats.update(_read_json(STATS_FILE))

    return stats


def reset_stats() -> None:
    with _lock:
        if STATS_FILE.exists():
            STATS_FILE.unlink()


# ==========================================
# Шаблоны субтитров пользователей
# ==========================================
#
# {"<user_id>": [{"id": "a1b2c3d4", "name": "...", "style": {...},
#                 "preview_text": "..."}, ...]}

def list_templates(user_id: int) -> list[dict]:
    with _lock:
        data = _read_json(TEMPLATES_FILE)

    templates = data.get(str(user_id), [])
    return [item for item in templates if isinstance(item, dict) and "id" in item]


def get_template(user_id: int, template_id: str) -> dict | None:
    return next(
        (item for item in list_templates(user_id) if item["id"] == template_id),
        None,
    )


def create_template(user_id: int, name: str, style: dict) -> dict:
    """
    Бросает ValueError, если достигнут лимит шаблонов.
    """

    template = {
        "id": secrets.token_hex(4),
        "name": name,
        "style": style,
        "preview_text": "",
    }

    with _lock:
        data = _read_json(TEMPLATES_FILE)
        templates = data.setdefault(str(user_id), [])

        if len(templates) >= MAX_TEMPLATES_PER_USER:
            raise ValueError(
                f"Можно хранить не больше {MAX_TEMPLATES_PER_USER} шаблонов."
            )

        templates.append(template)
        _write_json(TEMPLATES_FILE, data)

    return template


def update_template(user_id: int, template_id: str, **changes) -> dict | None:
    with _lock:
        data = _read_json(TEMPLATES_FILE)

        for template in data.get(str(user_id), []):
            if template.get("id") == template_id:
                template.update(changes)
                _write_json(TEMPLATES_FILE, data)
                return template

    return None


def delete_template(user_id: int, template_id: str) -> bool:
    with _lock:
        data = _read_json(TEMPLATES_FILE)
        templates = data.get(str(user_id), [])
        remaining = [item for item in templates if item.get("id") != template_id]

        if len(remaining) == len(templates):
            return False

        data[str(user_id)] = remaining
        _write_json(TEMPLATES_FILE, data)

    return True
