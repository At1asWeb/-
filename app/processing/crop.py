"""
Уникализация №3 — Crop и №4 — Zoom + Crop.

0. (только Zoom + Crop) Кадр приближается на 15% и обрезается
   по центру обратно до исходного размера.
1. Видео обрезается сверху и снизу на 15% (остаётся 70% высоты).
2. Если выбрано — обрезанное видео отзеркаливается.
3. Накладывается по центру на фон 1080x1920 (фон НЕ зеркалится).

Параметры обрезки/приближения и верхнюю границу области можно менять —
на этом же построен режим «Crop + Zoom 10% + видео сверху».
"""

from app.processing.background import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    FPS,
    background_filter,
)


CROP_PERCENT = 15
ZOOM_FACTOR = 1.15


def crop_filters(
    background_index: int,
    output_label: str,
    mirror: bool = True,
    zoom: bool = False,
    fps: str | int = FPS,
    crop_percent: float = CROP_PERCENT,
    zoom_factor: float = ZOOM_FACTOR,
    area_top: int = 0,
) -> tuple[list[str], tuple[int, int]]:
    """
    area_top — видео вписывается в область от area_top до низа кадра
    и центрируется в ней (0 — весь кадр, как раньше).
    """

    keep = 1 - 2 * crop_percent / 100
    mirror_part = ",hflip" if mirror else ""
    area_height = CANVAS_HEIGHT - area_top

    # Приближение: увеличиваем кадр и режем по центру до исходного размера.
    zoom_part = (
        f"scale=trunc(iw*{zoom_factor}/2)*2:trunc(ih*{zoom_factor}/2)*2:"
        "flags=lanczos,"
        f"crop=trunc(iw/{zoom_factor}/2)*2:trunc(ih/{zoom_factor}/2)*2,"
        if zoom
        else ""
    )

    filters = [
        background_filter(background_index, "[bg]", fps),
        (
            "[0:v]"
            f"fps={fps},"
            f"{zoom_part}"
            # Обрезка сверху и снизу, высота чётная.
            f"crop=iw:trunc(ih*{keep}/2)*2:0:trunc(ih*{crop_percent / 100}/2)*2,"
            # Вписываем в ширину кадра, не выходя за высоту области.
            f"scale={CANVAS_WIDTH}:{area_height}:"
            "force_original_aspect_ratio=decrease:"
            "force_divisible_by=2:flags=lanczos,"
            "setsar=1"
            f"{mirror_part}"
            "[fg]"
        ),
        (
            "[bg][fg]"
            f"overlay=x=(W-w)/2:y={area_top}+({area_height}-h)/2:shortest=1"
            f"{output_label}"
        ),
    ]

    return filters, (CANVAS_WIDTH, CANVAS_HEIGHT)
