"""
Уникализация №5 — Crop + Zoom 10% + видео сверху.

1. Исходник приближается на 10% и обрезается сверху и снизу на 10%
   (если выбрано — отзеркаливается).
2. Случайное видео из assets/overlays накладывается сверху кадра:
   всегда на всю ширину 1080, от верхнего края вниз на заданную высоту
   (настройка «Видео сверху» в админке). Видео заполняет эту область
   целиком, лишнее обрезается по центру; звук не используется,
   короткое видео зацикливается. Наложение НЕ зеркалится.
3. Основное видео вписывается в оставшуюся область под наложением,
   поэтому наложение его не перекрывает.
Субтитры, баннер и картинка в конце идут поверх, как в остальных режимах.
"""

from pathlib import Path

from app.config import settings
from app.processing.background import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    FPS,
    background_input_arguments,
)
from app.processing.crop import crop_filters
from app.processing.library import list_assets, random_asset
from app.processing.media import ensure_output, even, run_ffmpeg
from app.storage import get_runtime


CROP_PERCENT = 10
ZOOM_FACTOR = 1.10


def overlay_height(percent: float | None = None) -> int:
    if percent is None:
        percent = get_runtime()["top_overlay_height_percent"]

    return even(CANVAS_HEIGHT * percent / 100)


def pick_overlay_video() -> Path:
    overlay_file = random_asset("overlays")

    if overlay_file is None:
        raise FileNotFoundError(
            "Нет видео для наложения сверху. "
            "Добавьте их в админ-панели (🎞 Видео сверху) "
            "или в папку assets/overlays."
        )

    return overlay_file


def overlay_input_arguments(overlay_file: Path) -> list[str]:
    return ["-stream_loop", "-1", "-i", str(overlay_file)]


def top_overlay_filters(
    background_index: int,
    overlay_index: int,
    output_label: str,
    mirror: bool = True,
    fps: str | int = FPS,
    height: int | None = None,
) -> tuple[list[str], tuple[int, int]]:
    top = overlay_height() if height is None else height

    filters, size = crop_filters(
        background_index=background_index,
        output_label="[topbase]",
        mirror=mirror,
        zoom=True,
        fps=fps,
        crop_percent=CROP_PERCENT,
        zoom_factor=ZOOM_FACTOR,
        area_top=top,
    )

    filters += [
        (
            f"[{overlay_index}:v]"
            f"fps={fps},"
            f"scale={CANVAS_WIDTH}:{top}:"
            "force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={CANVAS_WIDTH}:{top},"
            "setsar=1,"
            "format=yuv420p"
            "[topvideo]"
        ),
        # shortest=1: зацикленное наложение заканчивается вместе с основным видео.
        f"[topbase][topvideo]overlay=x=0:y=0:shortest=1{output_label}",
    ]

    return filters, size


def render_top_overlay_preview(output_file: Path) -> tuple[Path, Path, int]:
    """
    Кадр 1080x1920 с текущей высотой наложения, собранный той же цепочкой
    фильтров, что и обработка. Вместо исходника — тестовое изображение.
    Возвращает (PNG 540x960, файл наложения, высоту в px).
    """

    overlays = list_assets("overlays")

    if not overlays:
        raise FileNotFoundError("Нет видео для наложения.")

    overlay_file = overlays[0]
    height = overlay_height()

    inputs = ["-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=2"]

    if list_assets("backgrounds"):
        background_arguments, _ = background_input_arguments()
        inputs += background_arguments
    else:
        inputs += ["-f", "lavfi", "-i", "color=c=0x262626:s=1080x1920:r=30:d=2"]

    inputs += ["-ss", "1", *overlay_input_arguments(overlay_file)]

    filters, _ = top_overlay_filters(
        background_index=1,
        overlay_index=2,
        output_label="[frame]",
        mirror=False,
        fps=30,
        height=height,
    )

    filters.append(
        f"[frame]drawbox=x=0:y={height - 3}:w={CANVAS_WIDTH}:h=6:"
        "color=yellow@0.9:t=fill,scale=540:960[final]"
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[final]",
            "-ss",
            "0.5",
            "-frames:v",
            "1",
            str(output_file),
        ],
        error_message="Не удалось построить предпросмотр видео сверху",
        cwd=settings.base_dir,
        timeout=120,
    )

    return ensure_output(output_file, "Предпросмотр видео сверху"), overlay_file, height
