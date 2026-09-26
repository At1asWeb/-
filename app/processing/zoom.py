"""
Уникализация №2 — Zoom +15%.

Кадр увеличивается на 15% и обрезается по центру
обратно до исходного размера.
"""

from app.processing.media import even


ZOOM_FACTOR = 1.15

# Максимальная ширина результата (для 4K-исходников).
MAX_WIDTH = 1080


def zoom_filters(
    source_width: int,
    source_height: int,
    output_label: str,
) -> tuple[list[str], tuple[int, int]]:

    if source_width > MAX_WIDTH:
        target_width = even(MAX_WIDTH)
        target_height = even(source_height * MAX_WIDTH / source_width)
    else:
        target_width = even(source_width)
        target_height = even(source_height)

    zoom_width = even(target_width * ZOOM_FACTOR)
    zoom_height = even(target_height * ZOOM_FACTOR)

    filters = [
        (
            "[0:v]"
            f"scale={zoom_width}:{zoom_height}:flags=lanczos,"
            f"crop={target_width}:{target_height},"
            "setsar=1"
            f"{output_label}"
        ),
    ]

    return filters, (target_width, target_height)
