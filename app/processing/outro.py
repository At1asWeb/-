"""
Концовка — картинка из assets/outro в конце видео (по выбору пользователя):

- append  — картинка добавляется после видео на OUTRO_DURATION секунд;
- overlay — картинка накладывается поверх последних N секунд видео
            (звук и длительность не меняются).

В обоих режимах картинка идёт ПОСЛЕ всей цепочки эффектов (уникализация,
отзеркаливание, субтитры, баннер), поэтому ни зеркало, ни баннер,
ни субтитры на неё не накладываются.
"""

from pathlib import Path

from app.config import settings
from app.processing.background import FPS
from app.processing.media import IMAGE_EXTENSIONS


OUTRO_DURATION = 3.0

OUTRO_MODES = ("append", "overlay")

# Пределы для «поверх конца видео», сек.
OVERLAY_MIN_SECONDS = 0.5
OVERLAY_MAX_SECONDS = 30.0


def find_outro_image() -> Path | None:
    """
    Первая (по алфавиту) картинка из assets/outro или None, если папка пуста.
    """

    directory = settings.outro_dir

    if not directory.is_dir():
        return None

    images = sorted(
        (
            file
            for file in directory.iterdir()
            if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda file: file.name.lower(),
    )

    return images[0] if images else None


def outro_input_arguments(
    image_file: Path,
    fps: str | int = FPS,
    duration: float = OUTRO_DURATION,
) -> list[str]:
    return [
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-t",
        f"{duration:.3f}",
        "-i",
        str(image_file),
    ]


def _cover_filter(video_width: int, video_height: int) -> str:
    # Картинка всегда закрывает весь кадр: масштаб «с запасом» и обрезка
    # лишнего по центру, без полей. Картинка 9:16 (1080x1920) на вертикальном
    # видео ложится целиком, без обрезки.
    return (
        f"scale={video_width}:{video_height}:"
        "force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={video_width}:{video_height}"
    )


def _main_video_filter(video_label: str, video_duration: float, fps: str | int) -> str:
    # Основное видео приводится ровно к длительности исходника:
    # tpad добивает последний кадр, если видео короче звука,
    # trim обрезает бесконечный поток от зацикленного баннера.
    # Так картинка попадает точно в конец звука.
    return (
        f"{video_label}"
        f"fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={video_duration:.3f},"
        f"trim=duration={video_duration:.3f},"
        "setpts=PTS-STARTPTS,"
        "setsar=1,"
        "format=yuv420p"
        "[outro_main]"
    )


def outro_filters(
    video_label: str,
    input_index: int,
    video_width: int,
    video_height: int,
    video_duration: float,
    output_label: str,
    fps: str | int = FPS,
) -> list[str]:
    return [
        _main_video_filter(video_label, video_duration, fps),
        (
            f"[{input_index}:v]"
            f"{_cover_filter(video_width, video_height)},"
            "setsar=1,"
            f"fps={fps},"
            f"trim=duration={OUTRO_DURATION:.3f},"
            "setpts=PTS-STARTPTS,"
            "format=yuv420p"
            "[outro_image]"
        ),
        f"[outro_main][outro_image]concat=n=2:v=1:a=0{output_label}",
    ]


def outro_overlay_filters(
    video_label: str,
    input_index: int,
    video_width: int,
    video_height: int,
    video_duration: float,
    overlay_seconds: float,
    output_label: str,
    fps: str | int = FPS,
) -> list[str]:
    """
    Картинка поверх последних overlay_seconds секунд видео, на весь кадр.
    Сквозь прозрачные места PNG видно видео.
    """

    start = max(0.0, video_duration - overlay_seconds)

    return [
        _main_video_filter(video_label, video_duration, fps),
        (
            f"[{input_index}:v]"
            f"{_cover_filter(video_width, video_height)},"
            "setsar=1,"
            f"fps={fps},"
            "format=rgba,"
            # Сдвигаем картинку на момент начала наложения.
            f"setpts=PTS-STARTPTS+{start:.3f}/TB"
            "[outro_image]"
        ),
        (
            "[outro_main][outro_image]"
            "overlay=x=(W-w)/2:y=(H-h)/2:eof_action=pass:format=auto,"
            "format=yuv420p"
            f"{output_label}"
        ),
    ]
