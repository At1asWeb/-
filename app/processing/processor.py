"""
Главный конвейер обработки видео.

Порядок обработки строго фиксирован:

    1. Уникализация   — Circle, Zoom +15%, Crop 15% или Zoom + Crop 15%
    2. Отзеркаливание — по выбору пользователя:
                        hflip всего кадра (Circle, Zoom);
                        в Crop зеркалится только видео, до наложения на фон
    3. Субтитры       — поверх уже обработанного видео (текст читается)
    4. Баннер         — поверх всего (баннер не зеркалится)
    5. Концовка       — картинка из assets/outro на 3 сек в конце
                        (без зеркала, субтитров и баннера)
    +  Фоновая музыка

Всё выполняется одним проходом FFmpeg (одно перекодирование = без
потери качества), но цепочка фильтров строится именно в таком порядке.

Речь для субтитров распознаётся по ОРИГИНАЛЬНОЙ звуковой дорожке
(без фоновой музыки) — так Whisper работает точнее.
Тайминги совпадают, так как длительность не меняется.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.config import settings
from app.processing.banner import (
    banner_filters,
    banner_input_arguments,
    get_banner_by_name,
)
from app.processing.background import background_input_arguments
from app.processing.circle import circle_filters
from app.processing.crop import crop_filters
from app.processing.media import (
    ensure_output,
    file_size_mb,
    get_duration,
    get_video_size,
    has_audio,
    run_ffmpeg,
)
from app.processing.music import pick_music
from app.processing.outro import (
    OUTRO_DURATION,
    find_outro_image,
    outro_filters,
    outro_input_arguments,
)
from app.processing.subtitle_formatter import format_srt
from app.processing.subtitles import (
    NoSpeechError,
    generate_subtitles,
    srt_to_ass,
)
from app.processing.zoom import zoom_filters


MODES = {
    "circle": "⭕ Circle",
    "zoom": "🔍 Zoom +15%",
    "crop": "✂️ Crop 15%",
    "zoom_crop": "🔍✂️ Zoom + Crop 15%",
}

# Режимы, которые используют фоновое видео из assets/backgrounds.
BACKGROUND_MODES = {"circle", "crop", "zoom_crop"}

# Режимы, где зеркалится только исходное видео (внутри своей цепочки),
# а не весь кадр вместе с фоном.
SELF_MIRRORED_MODES = {"crop", "zoom_crop"}


@dataclass
class ProcessingOptions:
    mode: str
    mirror: bool = True
    subtitles: bool = False
    banner_name: str | None = None
    outro: bool = True
    # Готовый (например, отредактированный вручную) SRT —
    # если задан, распознавание речи не запускается.
    subtitles_file: Path | None = None


@dataclass
class ProcessingResult:
    file: Path
    duration: float
    size_mb: float
    mode: str
    mirrored: bool
    subtitles_added: bool
    banner_added: bool
    outro_added: bool
    music_name: str | None
    notes: list[str] = field(default_factory=list)


ProgressCallback = Callable[[str], None]


NO_SPEECH_NOTE = "⚠️ Речь не распознана — субтитры не добавлены."


def prepare_subtitles(input_file: Path, work_dir: Path) -> Path | None:
    """
    Распознаёт речь и форматирует SRT. None — если речи нет.
    """

    work_dir.mkdir(parents=True, exist_ok=True)

    raw_srt = work_dir / "subtitles_raw.srt"
    formatted_srt = work_dir / "subtitles.srt"

    try:
        generate_subtitles(input_video=input_file, output_srt=raw_srt)

        try:
            format_srt(input_srt=raw_srt, output_srt=formatted_srt)
        except RuntimeError as error:
            # format_srt бросает RuntimeError, если текста нет.
            raise NoSpeechError(str(error)) from error

    except NoSpeechError as error:
        print(f"Субтитры пропущены: {error}")
        return None

    return formatted_srt


def process_video(
    input_file: Path,
    work_dir: Path,
    options: ProcessingOptions,
    progress: ProgressCallback | None = None,
) -> ProcessingResult:

    def report(text: str) -> None:
        print(f"[processing] {text}")

        if progress:
            progress(text)

    if options.mode not in MODES:
        raise ValueError(
            f"Неизвестный режим: {options.mode}. "
            f"Доступные: {', '.join(MODES)}"
        )

    if not input_file.exists():
        raise FileNotFoundError(f"Исходный файл не найден: {input_file}")

    work_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    notes: list[str] = []

    source_width, source_height = get_video_size(input_file)
    duration = get_duration(input_file)
    source_has_audio = has_audio(input_file)

    # ------------------------------------------
    # Субтитры: распознаём речь заранее
    # ------------------------------------------

    formatted_srt: Path | None = None

    if options.subtitles_file is not None:
        formatted_srt = options.subtitles_file

    elif options.subtitles:
        report("📝 Распознаю речь для субтитров…")

        formatted_srt = prepare_subtitles(input_file, work_dir)

        if formatted_srt is None:
            notes.append(NO_SPEECH_NOTE)

    # ------------------------------------------
    # Входы FFmpeg
    # ------------------------------------------

    inputs: list[str] = ["-i", str(input_file)]
    input_count = 1

    filters: list[str] = []

    # 1. Уникализация
    background_name = None
    background_index = None

    if options.mode in BACKGROUND_MODES:
        background_arguments, background_file = background_input_arguments()
        background_name = background_file.name

        inputs += background_arguments
        background_index = input_count
        input_count += 1

    if options.mode == "circle":
        uniq_filters, (width, height) = circle_filters(
            background_index=background_index,
            output_label="[uniq]",
        )

    elif options.mode in ("crop", "zoom_crop"):
        uniq_filters, (width, height) = crop_filters(
            background_index=background_index,
            output_label="[uniq]",
            mirror=options.mirror,
            zoom=options.mode == "zoom_crop",
        )

    else:
        uniq_filters, (width, height) = zoom_filters(
            source_width=source_width,
            source_height=source_height,
            output_label="[uniq]",
        )

    filters += uniq_filters

    # 2. Отзеркаливание (по выбору пользователя) — строго после уникализации.
    # В Crop зеркалится только видео, до наложения на фон (внутри crop_filters).
    if options.mirror and options.mode not in SELF_MIRRORED_MODES:
        filters.append("[uniq]hflip[mirrored]")
        current = "[mirrored]"
    else:
        current = "[uniq]"

    # 3. Субтитры — поверх отзеркаленного кадра
    ass_file: Path | None = None

    if formatted_srt is not None:
        ass_file = srt_to_ass(
            input_srt=formatted_srt,
            output_ass=work_dir / "subtitles.ass",
            video_width=width,
            video_height=height,
        )

        # Относительный путь без «:» — FFmpeg запускается из корня проекта.
        ass_relative = ass_file.resolve().relative_to(
            settings.base_dir.resolve()
        ).as_posix()

        filters.append(f"{current}ass=filename='{ass_relative}'[subbed]")
        current = "[subbed]"

    # 4. Баннер — последним слоем
    banner_file = None

    if options.banner_name:
        banner_file = get_banner_by_name(options.banner_name)

        inputs += banner_input_arguments(banner_file)

        banner_chain, _ = banner_filters(
            banner_file=banner_file,
            input_index=input_count,
            video_label=current,
            video_width=width,
            video_height=height,
            output_label="[bannered]",
        )
        input_count += 1

        filters += banner_chain
        current = "[bannered]"

    # 5. Концовка — приклеивается после всех эффектов
    outro_file = find_outro_image() if options.outro else None
    total_duration = duration

    if outro_file is not None:
        inputs += outro_input_arguments(outro_file)

        filters += outro_filters(
            video_label=current,
            input_index=input_count,
            video_width=width,
            video_height=height,
            video_duration=duration,
            output_label="[with_outro]",
        )
        input_count += 1

        current = "[with_outro]"
        total_duration = duration + OUTRO_DURATION

    filters.append(f"{current}format=yuv420p[vout]")

    # ------------------------------------------
    # Звук: оригинал + фоновая музыка
    # ------------------------------------------

    music_file, music_volume = pick_music()
    audio_map: str | None = None

    if music_file is not None:
        inputs += ["-stream_loop", "-1", "-i", str(music_file)]
        music_index = input_count
        input_count += 1

        # Музыка звучит и под концовкой, затухая к самому концу.
        fade_start = max(0.0, total_duration - 1.0)

        filters.append(
            f"[{music_index}:a]"
            "aresample=48000,"
            f"volume={music_volume:.4f},"
            f"atrim=duration={total_duration:.3f},"
            "asetpts=N/SR/TB,"
            f"afade=t=out:st={fade_start:.3f}:d=1"
            "[music]"
        )

        if source_has_audio:
            # Оригинальный звук дополняется тишиной на время концовки.
            filters.append(
                "[0:a]aresample=48000,"
                f"apad=whole_dur={total_duration:.3f}[orig];"
                "[orig][music]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0[aout]"
            )
        else:
            filters.append("[music]anull[aout]")

        audio_map = "[aout]"

    elif source_has_audio and outro_file is not None:
        filters.append(
            f"[0:a]apad=whole_dur={total_duration:.3f}[aout]"
        )
        audio_map = "[aout]"

    elif source_has_audio:
        audio_map = "0:a:0"

    # ------------------------------------------
    # Сборка команды
    # ------------------------------------------

    output_file = work_dir / "result.mp4"

    arguments = [
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
    ]

    if audio_map:
        arguments += ["-map", audio_map, "-c:a", "aac", "-b:a", "192k"]
    else:
        arguments += ["-an"]

    arguments += [
        "-t",
        f"{total_duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        str(output_file),
    ]

    print("\n=== ПАРАМЕТРЫ ОБРАБОТКИ ===")
    print(f"Режим:       {MODES[options.mode]}")
    print(f"Исходник:    {source_width}x{source_height}, {duration:.2f} сек")
    print(f"Результат:   {width}x{height}")
    if background_name:
        print(f"Фон:         {background_name}")
    print(f"Зеркало:     {'да' if options.mirror else 'нет'}")
    print(f"Субтитры:    {'да' if ass_file else 'нет'}")
    print(f"Баннер:      {banner_file.name if banner_file else 'нет'}")
    print(f"Концовка:    {outro_file.name if outro_file else 'нет'}")
    print(
        f"Музыка:      "
        f"{f'{music_file.name} ({music_volume * 100:.1f}%)' if music_file else 'нет'}"
    )
    print("===========================\n")

    report(f"🎬 Обрабатываю видео ({MODES[options.mode]})…")

    run_ffmpeg(
        arguments,
        error_message="FFmpeg не смог обработать видео",
        cwd=settings.base_dir,
    )

    ensure_output(output_file, "Обработка видео")

    # ------------------------------------------
    # Сжатие под лимит Telegram
    # ------------------------------------------

    limit_mb = min(settings.max_output_size_mb, settings.telegram_upload_limit_mb)

    if file_size_mb(output_file) > limit_mb:
        report("🗜 Файл слишком большой, сжимаю…")
        output_file = _compress_to_limit(
            input_file=output_file,
            output_file=work_dir / "result_compressed.mp4",
            duration=total_duration,
            limit_mb=limit_mb,
            has_audio_track=audio_map is not None,
        )

    elapsed = time.monotonic() - started

    print(
        f"=== ГОТОВО за {elapsed:.1f} сек: "
        f"{output_file.name}, {file_size_mb(output_file):.2f} MB ==="
    )

    return ProcessingResult(
        file=output_file,
        duration=total_duration,
        size_mb=file_size_mb(output_file),
        mode=options.mode,
        mirrored=options.mirror,
        subtitles_added=ass_file is not None,
        banner_added=banner_file is not None,
        outro_added=outro_file is not None,
        music_name=music_file.name if music_file else None,
        notes=notes,
    )


def _compress_to_limit(
    input_file: Path,
    output_file: Path,
    duration: float,
    limit_mb: float,
    has_audio_track: bool,
) -> Path:
    """
    Перекодирует видео с целевым битрейтом так,
    чтобы файл уложился в лимит (с запасом 7%).
    """

    audio_kbps = 128 if has_audio_track else 0
    total_kbps = limit_mb * 0.93 * 8 * 1024 / duration
    video_kbps = int(total_kbps - audio_kbps)

    if video_kbps < 300:
        raise RuntimeError(
            "Видео слишком длинное: его невозможно сжать "
            f"до {limit_mb:.0f} MB с приемлемым качеством."
        )

    arguments = [
        "-i",
        str(input_file),
        "-map",
        "0:v:0",
    ]

    if has_audio_track:
        arguments += ["-map", "0:a:0", "-c:a", "aac", "-b:a", f"{audio_kbps}k"]

    arguments += [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{int(video_kbps * 1.2)}k",
        "-bufsize",
        f"{video_kbps * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_file),
    ]

    run_ffmpeg(arguments, error_message="Не удалось сжать видео")
    ensure_output(output_file, "Сжатие видео")

    input_file.unlink(missing_ok=True)

    return output_file
