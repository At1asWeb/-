"""
Рекламный баннер: геометрия и аргументы FFmpeg.

Поддерживаются:
- статичные картинки (PNG / JPG / WEBP) — зацикливаются как кадр;
- GIF — анимация зацикливается;
- видео (MP4 / WEBM / MOV) — зацикливается, если BANNER_LOOP=true.
"""

from pathlib import Path

from app.config import settings
from app.processing.library import get_asset
from app.processing.media import (
    GIF_EXTENSIONS,
    IMAGE_EXTENSIONS,
    even,
    get_video_size,
)
from app.storage import get_runtime


def get_banner_by_name(name: str) -> Path:
    return get_asset("banners", name)


def calculate_banner_geometry(
    banner_width: int,
    banner_height: int,
    video_width: int,
    video_height: int,
) -> dict:
    """
    Размер и позиция баннера относительно видео.

    Настройки (админ-панель → Настройки или .env):

    - banner_width_percent  — ширина области баннера, % от ширины видео;
    - banner_height_percent — высота области, % от высоты видео
                              (0 = авто: по пропорциям баннера);
    - banner_fit            — как вписать баннер в область:
        fit     — целиком, без искажений (может стать уже/ниже области);
        crop    — заполнить область целиком, лишние края обрезаются;
        stretch — растянуть точно под область (возможны искажения);
    - banner_top_offset_percent — отступ сверху, % от высоты видео.

    Баннер всегда по центру по горизонтали и не выходит за кадр.
    """

    if banner_width <= 0 or banner_height <= 0:
        raise ValueError("Размеры баннера должны быть больше нуля.")

    if video_width <= 0 or video_height <= 0:
        raise ValueError("Размеры видео должны быть больше нуля.")

    runtime = get_runtime()

    width_percent = runtime["banner_width_percent"]
    height_percent = runtime["banner_height_percent"]
    fit = runtime["banner_fit"]
    top_percent = runtime["banner_top_offset_percent"]
    opacity = runtime["banner_opacity"]

    box_width = even(video_width * width_percent / 100)
    banner_ratio = banner_height / banner_width

    crop_filter = None

    if height_percent <= 0:
        # Авто: высота по пропорциям, но не больше половины кадра.
        fit = "auto"
        target_width = box_width
        target_height = even(box_width * banner_ratio)

        max_height = even(video_height * 0.5)

        if target_height > max_height:
            target_height = max_height
            target_width = even(target_height / banner_ratio)

        scale_width, scale_height = target_width, target_height

    else:
        box_height = even(video_height * height_percent / 100)
        box_ratio = box_height / box_width

        if fit == "stretch":
            target_width, target_height = box_width, box_height
            scale_width, scale_height = target_width, target_height

        elif fit == "crop":
            # Масштабируем так, чтобы покрыть область, и режем по центру.
            if banner_ratio > box_ratio:
                scale_width = box_width
                scale_height = even(box_width * banner_ratio)
            else:
                scale_height = box_height
                scale_width = even(box_height / banner_ratio)

            target_width, target_height = box_width, box_height
            crop_filter = f"crop={target_width}:{target_height}"

        else:
            # fit: вписываем целиком внутрь области.
            if banner_ratio > box_ratio:
                target_height = box_height
                target_width = even(box_height / banner_ratio)
            else:
                target_width = box_width
                target_height = even(box_width * banner_ratio)

            scale_width, scale_height = target_width, target_height

    x = even((video_width - target_width) / 2)
    y = even(video_height * top_percent / 100)

    if y + target_height > video_height:
        y = even(max(0, video_height - target_height))

    return {
        "width": target_width,
        "height": target_height,
        "scale_width": scale_width,
        "scale_height": scale_height,
        "crop": crop_filter,
        "x": x,
        "y": y,
        "opacity": opacity,
        "fit": fit,
    }


def banner_input_arguments(banner_file: Path) -> list[str]:
    """
    Аргументы -i для баннера в зависимости от его типа.
    """

    extension = banner_file.suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        return ["-loop", "1", "-i", str(banner_file)]

    if extension in GIF_EXTENSIONS:
        ignore_loop = "0" if settings.banner_loop else "1"
        return ["-ignore_loop", ignore_loop, "-i", str(banner_file)]

    if settings.banner_loop:
        return ["-stream_loop", "-1", "-i", str(banner_file)]

    return ["-i", str(banner_file)]


def banner_filters(
    banner_file: Path,
    input_index: int,
    video_label: str,
    video_width: int,
    video_height: int,
    output_label: str,
) -> tuple[list[str], dict]:
    """
    Возвращает цепочки filter_complex для наложения баннера
    и рассчитанную геометрию.
    """

    banner_width, banner_height = get_video_size(banner_file)

    geometry = calculate_banner_geometry(
        banner_width=banner_width,
        banner_height=banner_height,
        video_width=video_width,
        video_height=video_height,
    )

    crop_part = f"{geometry['crop']}," if geometry["crop"] else ""

    filters = [
        (
            f"[{input_index}:v]"
            f"scale={geometry['scale_width']}:{geometry['scale_height']}:"
            "flags=lanczos,"
            f"{crop_part}"
            "setsar=1,"
            "format=rgba,"
            f"colorchannelmixer=aa={geometry['opacity']:.2f}"
            "[banner]"
        ),
        (
            f"{video_label}[banner]"
            "overlay="
            f"x={geometry['x']}:"
            f"y={geometry['y']}:"
            "eof_action=repeat:"
            "format=auto"
            f"{output_label}"
        ),
    ]

    return filters, geometry


def render_banner_preview(
    banner_file: Path,
    output_file: Path,
    video_width: int = 1080,
    video_height: int = 1920,
) -> tuple[Path, dict]:
    """
    Рисует баннер на сером кадре 1080x1920 с текущими настройками.
    Пунктиром-рамкой показана настроенная область баннера.
    Возвращает PNG (уменьшенный до 540x960) и геометрию.
    """

    from app.processing.media import run_ffmpeg

    output_file.parent.mkdir(parents=True, exist_ok=True)

    runtime = get_runtime()

    # Рамка области — только если высота задана вручную.
    box_filter = ""

    if runtime["banner_height_percent"] > 0:
        box_width = even(video_width * runtime["banner_width_percent"] / 100)
        box_height = even(video_height * runtime["banner_height_percent"] / 100)
        box_x = even((video_width - box_width) / 2)
        box_y = even(video_height * runtime["banner_top_offset_percent"] / 100)

        if box_y + box_height > video_height:
            box_y = even(max(0, video_height - box_height))

        box_filter = (
            f",drawbox=x={box_x}:y={box_y}:w={box_width}:h={box_height}:"
            "color=yellow@0.9:t=4"
        )

    # Для видео/GIF берём кадр, где анимация появления уже закончилась.
    banner_input = ["-i", str(banner_file)]

    if banner_file.suffix.lower() not in IMAGE_EXTENSIONS:
        from app.processing.media import get_duration

        try:
            seek = min(3.0, get_duration(banner_file) / 2)
        except RuntimeError:
            seek = 0.0

        banner_input = ["-ss", f"{seek:.2f}", *banner_input]

    filters, geometry = banner_filters(
        banner_file=banner_file,
        input_index=0,
        video_label="[bg]",
        video_width=video_width,
        video_height=video_height,
        output_label="[out]",
    )

    graph = ";".join(
        [
            f"color=c=0x3a3a3a:s={video_width}x{video_height}:d=1,"
            # Сетка, чтобы было видно масштаб.
            "drawgrid=w=iw/10:h=ih/10:t=1:color=white@0.15"
            f"{box_filter}"
            "[bg]",
            *filters,
            "[out]scale=540:960[final]",
        ]
    )

    run_ffmpeg(
        [
            *banner_input,
            "-filter_complex",
            graph,
            "-map",
            "[final]",
            "-frames:v",
            "1",
            str(output_file),
        ],
        error_message="Не удалось построить предпросмотр баннера",
    )

    return output_file, geometry
