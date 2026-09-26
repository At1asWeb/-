"""
Фоновая музыка для этапа уникализации.
"""

from pathlib import Path

from app.processing.library import random_asset
from app.storage import get_runtime


def pick_music() -> tuple[Path | None, float]:
    """
    Возвращает (файл, громкость 0..1) или (None, 0),
    если музыка выключена в настройках или библиотека пуста.
    """

    runtime = get_runtime()

    if not runtime["music_enabled"]:
        return None, 0.0

    music_file = random_asset("music")

    if music_file is None:
        return None, 0.0

    return music_file, runtime["music_volume_percent"] / 100
