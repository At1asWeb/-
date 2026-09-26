"""
Субтитры:

1. generate_subtitles — распознавание речи через фильтр whisper (whisper.cpp).
2. srt_to_ass        — конвертация отформатированного SRT в ASS
                       с пиксельной разметкой под размер итогового видео.
"""

import os
import re
from pathlib import Path

from app.config import settings
from app.processing.media import ensure_output, has_audio, run_ffmpeg


WHISPER_MODEL = settings.models_dir / "ggml-small.bin"

# Базовые параметры стиля для кадра 1080x1920.
BASE_WIDTH = 1080
BASE_HEIGHT = 1920
BASE_FONT_SIZE = 68
BASE_OUTLINE = 6
BASE_MARGIN_H = 90
BASE_MARGIN_BOTTOM = 290

FONT_NAME = "Arial"
PRIMARY_COLOUR = "&H00FFFFFF"   # белый
OUTLINE_COLOUR = "&H00CC00FF"   # розово-фиолетовый (BGR)


class NoSpeechError(RuntimeError):
    """В видео нет звука или речь не распознана."""


def generate_subtitles(
    input_video: Path,
    output_srt: Path,
) -> Path:

    if not input_video.exists():
        raise FileNotFoundError(f"Видео не найдено: {input_video}")

    if not WHISPER_MODEL.exists():
        raise FileNotFoundError(f"Модель Whisper не найдена: {WHISPER_MODEL}")

    if not has_audio(input_video):
        raise NoSpeechError("В видео нет звуковой дорожки.")

    output_srt.parent.mkdir(parents=True, exist_ok=True)

    if output_srt.exists():
        output_srt.unlink()

    project_dir = settings.base_dir

    # Параметры фильтра whisper не любят «:» из путей Windows,
    # поэтому передаём относительные пути и запускаем из корня проекта.
    model_path = os.path.relpath(WHISPER_MODEL, project_dir).replace("\\", "/")
    destination_path = os.path.relpath(output_srt, project_dir).replace("\\", "/")

    run_ffmpeg(
        [
            "-i",
            str(input_video),
            "-vn",
            "-af",
            (
                "aresample=16000,"
                "whisper="
                f"model={model_path}:"
                f"language={settings.whisper_language}:"
                f"destination={destination_path}:"
                "format=srt:"
                "use_gpu=false"
            ),
            "-f",
            "null",
            "-",
        ],
        error_message="FFmpeg не смог сгенерировать субтитры",
        cwd=project_dir,
    )

    if not output_srt.exists() or not output_srt.read_text(
        encoding="utf-8",
        errors="replace",
    ).strip():
        raise NoSpeechError("Речь в видео не распознана.")

    return output_srt


# ==========================================
# SRT -> ASS
# ==========================================

def _srt_time_to_ass(value: str) -> str:
    hours, minutes, rest = value.strip().split(":")
    seconds, milliseconds = rest.split(",")

    centiseconds = int(milliseconds) // 10

    return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "(").replace("}", ")")
    return text.replace("\n", "\\N")


def srt_to_ass(
    input_srt: Path,
    output_ass: Path,
    video_width: int,
    video_height: int,
) -> Path:

    content = input_srt.read_text(encoding="utf-8", errors="replace").strip()

    blocks = re.split(r"\n\s*\n", content)

    scale = min(video_width / BASE_WIDTH, video_height / BASE_HEIGHT)
    scale = max(scale, 0.3)

    font_size = round(BASE_FONT_SIZE * scale)
    outline = max(1, round(BASE_OUTLINE * scale))
    margin_h = round(BASE_MARGIN_H * video_width / BASE_WIDTH)
    margin_v = round(BASE_MARGIN_BOTTOM * video_height / BASE_HEIGHT)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT_NAME},{font_size},{PRIMARY_COLOUR},"
        f"{PRIMARY_COLOUR},{OUTLINE_COLOUR},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"{margin_h},{margin_h},{margin_v},204\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    events = []

    for block in blocks:
        lines = block.strip().splitlines()

        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )

        if timing_index is None:
            continue

        start_text, end_text = lines[timing_index].split("-->")
        text = "\n".join(lines[timing_index + 1:]).strip()

        if not text:
            continue

        events.append(
            "Dialogue: 0,"
            f"{_srt_time_to_ass(start_text)},"
            f"{_srt_time_to_ass(end_text)},"
            "Default,,0,0,0,,"
            f"{_escape_ass_text(text)}"
        )

    if not events:
        raise NoSpeechError("Субтитры пустые.")

    output_ass.parent.mkdir(parents=True, exist_ok=True)
    output_ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")

    return ensure_output(output_ass, "ASS-субтитры")
