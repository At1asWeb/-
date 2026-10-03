"""
Уникализация №1 — Circle.

Исходное видео вписывается в круг с мягким краем
по центру вертикального кадра 1080x1920.
Фон — случайное видео из assets/backgrounds.
"""

from app.processing.background import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    FPS,
    background_filter,
)


CIRCLE_SIZE = 1080

# Ширина сглаженного края круга в пикселях.
EDGE_SOFTNESS = 2.0


def circle_filters(
    background_index: int,
    output_label: str,
    fps: str | int = FPS,
) -> tuple[list[str], tuple[int, int]]:
    """
    Возвращает цепочки filter_complex и итоговый размер кадра.
    """

    radius = CIRCLE_SIZE / 2
    center = (CIRCLE_SIZE - 1) / 2

    circle_x = (CANVAS_WIDTH - CIRCLE_SIZE) // 2
    circle_y = (CANVAS_HEIGHT - CIRCLE_SIZE) // 2

    # Маска считается один раз и повторяется для всех кадров —
    # это многократно быстрее, чем geq на каждом кадре.
    mask_expression = (
        f"255*clip(({radius}-hypot(X-{center},Y-{center}))"
        f"/{EDGE_SOFTNESS},0,1)"
    )

    filters = [
        background_filter(background_index, "[bg]", fps),
        (
            "[0:v]"
            f"fps={fps},"
            f"scale={CIRCLE_SIZE}:{CIRCLE_SIZE}:"
            "force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={CIRCLE_SIZE}:{CIRCLE_SIZE},"
            "setsar=1,"
            "format=yuva420p"
            "[fg]"
        ),
        (
            f"color=c=black:s={CIRCLE_SIZE}x{CIRCLE_SIZE}:r={fps}:d=1,"
            "format=gray,"
            f"geq=lum='{mask_expression}',"
            "loop=loop=-1:size=1"
            "[mask]"
        ),
        "[fg][mask]alphamerge[circle]",
        (
            "[bg][circle]"
            f"overlay=x={circle_x}:y={circle_y}:shortest=1"
            f"{output_label}"
        ),
    ]

    return filters, (CANVAS_WIDTH, CANVAS_HEIGHT)
