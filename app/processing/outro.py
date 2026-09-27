"""
Концовка — картинка из assets/outro, добавляемая в конец каждого видео.

Картинка приклеивается ПОСЛЕ всей цепочки эффектов (уникализация,
отзеркаливание, субтитры, баннер), поэтому ни зеркало, ни баннер,
ни субтитры на неё не накладываются.
"""

from pathlib import Path

from app.config import settings
from app.processing.background import FPS
from app.processing.media import IMAGE_EXTENSIONS


OUTRO_DURATION = 3.0


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


def outro_input_arguments(image_file: Path, fps: str | int = FPS) -> list[str]:
    return [
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-t",
        f"{OUTRO_DURATION:.3f}",
        "-i",
        str(image_file),
    ]


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
        # Основное видео приводится ровно к длительности исходника:
        # tpad добивает последний кадр, если видео короче звука,
        # trim обрезает бесконечный поток от зацикленного баннера.
        # Так картинка начинается ровно там, где кончается звук.
        (
            f"{video_label}"
            f"fps={fps},"
            f"tpad=stop_mode=clone:stop_duration={video_duration:.3f},"
            f"trim=duration={video_duration:.3f},"
            "setpts=PTS-STARTPTS,"
            "setsar=1,"
            "format=yuv420p"
            "[outro_main]"
        ),
        # Картинка вписывается в кадр без искажений, поля — чёрные.
        (
            f"[{input_index}:v]"
            f"scale={video_width}:{video_height}:"
            "force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={video_width}:{video_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "setsar=1,"
            f"fps={fps},"
            f"trim=duration={OUTRO_DURATION:.3f},"
            "setpts=PTS-STARTPTS,"
            "format=yuv420p"
            "[outro_image]"
        ),
        f"[outro_main][outro_image]concat=n=2:v=1:a=0{output_label}",
    ]
