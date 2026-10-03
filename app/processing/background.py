"""
Фоновое видео для режимов, где исходник кладётся на фон
(Circle, Crop). Фон — случайный файл из assets/backgrounds,
растягивается на вертикальный кадр 1080x1920 и зацикливается.
"""

from pathlib import Path

from app.processing.library import random_asset


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
FPS = 30


def background_input_arguments() -> tuple[list[str], Path]:
    background_file = random_asset("backgrounds")

    if background_file is None:
        raise FileNotFoundError(
            "Нет фоновых видео. "
            "Добавьте их в админ-панели (🌄 Фоны) "
            "или в папку assets/backgrounds."
        )

    return (
        ["-stream_loop", "-1", "-i", str(background_file)],
        background_file,
    )


def background_filter(
    background_index: int,
    output_label: str,
    fps: str | int = FPS,
) -> str:
    return (
        f"[{background_index}:v]"
        f"scale={CANVAS_WIDTH}:{CANVAS_HEIGHT}:"
        "force_original_aspect_ratio=increase,"
        f"crop={CANVAS_WIDTH}:{CANVAS_HEIGHT},"
        "setsar=1,"
        f"fps={fps},"
        "format=yuv420p"
        f"{output_label}"
    )
