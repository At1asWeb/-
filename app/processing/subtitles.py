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
from app.processing.subtitle_style import (
    color_to_ass,
    default_style,
    fonts_dir_option,
    normalize_style,
)


WHISPER_MODEL = settings.models_dir / "ggml-small.bin"

# Размер и отступы стиля задаются для кадра 1080x1920
# и масштабируются под реальный размер видео.
BASE_WIDTH = 1080
BASE_HEIGHT = 1920

SAMPLE_TEXT = "Так будут выглядеть субтитры на вашем видео"


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
    style: dict | None = None,
) -> Path:
    """
    style — стиль шаблона пользователя; None — стандартный из админки.
    """

    content = input_srt.read_text(encoding="utf-8", errors="replace").strip()

    blocks = re.split(r"\n\s*\n", content)

    style = normalize_style(style) if style is not None else default_style()

    primary_colour = color_to_ass(style["text_color"])
    outline_colour = color_to_ass(style["outline_color"])

    scale = min(video_width / BASE_WIDTH, video_height / BASE_HEIGHT)
    scale = max(scale, 0.3)

    font_size = round(style["font_size"] * scale)
    outline = (
        max(1, round(style["outline"] * scale))
        if style["outline"]
        else 0
    )
    shadow = round(style["shadow"] * scale)
    margin_h = round(video_width * style["margin_percent"] / 100)
    margin_v = round(video_height * style["bottom_offset_percent"] / 100)

    if style["box"]:
        # BorderStyle=3: плашка цвета обводки, Outline — её внутренний отступ.
        border_style = 3
        outline = max(outline, round(10 * scale))
        back_colour = color_to_ass(style["outline_color"], alpha=0x40)
    else:
        border_style = 1
        back_colour = "&H80000000"   # полупрозрачная чёрная тень

    bold = -1 if style["bold"] else 0
    italic = -1 if style["italic"] else 0

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        # Умный перенос: если строка шире кадра (крупный шрифт, широкие
        # поля), libass сам перенесёт её, а не обрежет краем кадра.
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style['font']},{font_size},{primary_colour},"
        f"{primary_colour},{outline_colour},{back_colour},"
        f"{bold},{italic},0,0,100,100,0,0,{border_style},{outline},{shadow},2,"
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

        if style["uppercase"]:
            text = text.upper()

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


# ==========================================
# ПРЕДПРОСМОТР
# ==========================================

def render_subtitles_preview(
    output_file: Path,
    banner_file: Path | None = None,
    video_width: int = BASE_WIDTH,
    video_height: int = BASE_HEIGHT,
    style: dict | None = None,
    sample_text: str | None = None,
) -> Path:
    """
    Рисует пример субтитров на сером кадре 1080x1920: со стилем шаблона
    или (style=None) со стандартными настройками из админки.
    Если передан баннер — он тоже рисуется, чтобы было видно пересечения.
    Жёлтая рамка — область, в которой переносится текст (боковые поля).
    Возвращает PNG 540x960.
    """

    from app.processing.banner import banner_filters
    from app.processing.media import IMAGE_EXTENSIONS, get_duration
    from app.processing.subtitle_formatter import format_srt

    style = normalize_style(style) if style is not None else default_style()
    text = " ".join((sample_text or SAMPLE_TEXT).split())

    work_dir = output_file.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    raw_srt = work_dir / f"{output_file.stem}_raw.srt"
    sample_srt = work_dir / f"{output_file.stem}.srt"
    sample_ass = work_dir / f"{output_file.stem}.ass"

    raw_srt.write_text(
        f"1\n00:00:00,000 --> 00:00:05,000\n{text}\n",
        encoding="utf-8",
    )

    try:
        # Те же переносы строк, что и на реальном видео.
        format_srt(
            input_srt=raw_srt,
            output_srt=sample_srt,
            max_length=style["max_line_length"],
        )
        srt_to_ass(sample_srt, sample_ass, video_width, video_height, style)

        margin_h = round(video_width * style["margin_percent"] / 100)
        margin_v = round(video_height * style["bottom_offset_percent"] / 100)

        # Путь без «:» — FFmpeg запускается из корня проекта (как в processor).
        ass_relative = sample_ass.resolve().relative_to(
            settings.base_dir.resolve()
        ).as_posix()

        inputs: list[str] = []
        graph = [
            f"color=c=0x3a3a3a:s={video_width}x{video_height}:d=1,"
            "drawgrid=w=iw/10:h=ih/10:t=1:color=white@0.15,"
            f"drawbox=x={margin_h}:y=0:w={video_width - 2 * margin_h}:"
            f"h={video_height}:color=yellow@0.5:t=3,"
            # Нижняя граница текста.
            f"drawbox=x=0:y={video_height - margin_v}:w={video_width}:h=3:"
            "color=yellow@0.8:t=fill"
            "[bg]",
        ]
        current = "[bg]"

        if banner_file is not None:
            banner_input = ["-i", str(banner_file)]

            if banner_file.suffix.lower() not in IMAGE_EXTENSIONS:
                try:
                    seek = min(3.0, get_duration(banner_file) / 2)
                except RuntimeError:
                    seek = 0.0

                banner_input = ["-ss", f"{seek:.2f}", *banner_input]

            inputs += banner_input

            filters, _ = banner_filters(
                banner_file=banner_file,
                input_index=0,
                video_label=current,
                video_width=video_width,
                video_height=video_height,
                output_label="[bannered]",
            )
            graph += filters
            current = "[bannered]"

        graph.append(
            f"{current}ass=filename='{ass_relative}'{fonts_dir_option()},"
            "scale=540:960[final]"
        )

        run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                ";".join(graph),
                "-map",
                "[final]",
                "-frames:v",
                "1",
                str(output_file),
            ],
            error_message="Не удалось построить предпросмотр субтитров",
            cwd=settings.base_dir,
        )

    finally:
        raw_srt.unlink(missing_ok=True)
        sample_srt.unlink(missing_ok=True)
        sample_ass.unlink(missing_ok=True)

    return ensure_output(output_file, "Предпросмотр субтитров")
