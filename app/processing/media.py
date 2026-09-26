"""
Общие утилиты для работы с FFmpeg / FFprobe.
"""

import json
import subprocess
from pathlib import Path

from app.config import settings


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

GIF_EXTENSIONS = {
    ".gif",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
}


class FFmpegError(RuntimeError):
    pass


def run_ffmpeg(
    arguments: list[str],
    error_message: str,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> None:
    """
    Запускает ffmpeg с переданными аргументами.

    При ошибке выводит хвост stderr в консоль
    и выбрасывает FFmpegError / TimeoutError.
    """

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *arguments,
    ]

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or settings.processing_timeout_seconds,
        )

    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            f"{error_message}: превышен лимит времени."
        ) from error

    if result.returncode != 0:
        stderr_tail = "\n".join(
            (result.stderr or "").strip().splitlines()[-15:]
        )

        print(
            f"\n=== FFMPEG ERROR ({result.returncode}) ===\n"
            f"{stderr_tail}\n"
            "=================================\n"
        )

        raise FFmpegError(
            f"{error_message}. Код возврата: {result.returncode}"
        )


def probe(file_path: Path) -> dict:
    """
    Возвращает JSON-описание медиафайла от ffprobe.
    """

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=60,
        )

    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise RuntimeError(
            f"Не удалось прочитать медиафайл: {file_path.name}"
        ) from error

    return json.loads(result.stdout or "{}")


def _first_stream(info: dict, codec_type: str) -> dict | None:
    for stream in info.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream

    return None


def get_duration(file_path: Path) -> float:
    info = probe(file_path)

    duration_text = info.get("format", {}).get("duration")

    if not duration_text:
        video = _first_stream(info, "video") or {}
        duration_text = video.get("duration")

    try:
        duration = float(duration_text)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Не удалось определить длительность: {file_path.name}"
        ) from error

    if duration <= 0:
        raise RuntimeError(
            f"Некорректная длительность: {file_path.name}"
        )

    return duration


def get_video_size(file_path: Path) -> tuple[int, int]:
    """
    Возвращает размер кадра с учётом поворота (rotation).
    """

    info = probe(file_path)
    video = _first_stream(info, "video")

    if video is None:
        raise RuntimeError(
            f"В файле нет видеопотока: {file_path.name}"
        )

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    if width <= 0 or height <= 0:
        raise RuntimeError(
            f"Некорректные размеры: {width}x{height}"
        )

    rotation = 0

    for side_data in video.get("side_data_list", []) or []:
        if "rotation" in side_data:
            rotation = int(side_data["rotation"])

    if abs(rotation) % 180 == 90:
        width, height = height, width

    return width, height


def get_video_codec(file_path: Path) -> str | None:
    video = _first_stream(probe(file_path), "video")

    if video is None:
        return None

    return video.get("codec_name")


def has_audio(file_path: Path) -> bool:
    return _first_stream(probe(file_path), "audio") is not None


def even(value: float) -> int:
    """
    Округляет вниз до чётного числа (требование yuv420p).
    """

    number = int(value)
    return max(2, number - number % 2)


def file_size_mb(file_path: Path) -> float:
    return file_path.stat().st_size / 1024 / 1024


def ensure_output(file_path: Path, description: str) -> Path:
    if not file_path.exists():
        raise RuntimeError(f"{description}: файл не создан.")

    if file_path.stat().st_size == 0:
        raise RuntimeError(f"{description}: файл пустой.")

    return file_path
