from pathlib import Path
import re


MAX_LINE_LENGTH = 30
MAX_LINES = 2

# Слова, после которых нежелательно заканчивать строку.
BAD_LINE_ENDINGS = {
    "и",
    "а",
    "но",
    "или",
    "что",
    "как",
    "же",
    "бы",
    "ли",
    "то",
    "для",
    "на",
    "в",
    "с",
    "к",
    "у",
    "по",
    "из",
    "за",
    "до",
    "от",
}

# Короткие слова, с которых нежелательно начинать вторую строку.
BAD_LINE_STARTS = {
    "и",
    "а",
    "но",
    "или",
    "что",
    "как",
    "же",
    "бы",
    "ли",
    "то",
}


def format_srt(input_srt: Path, output_srt: Path) -> Path:
    if not input_srt.exists():
        raise FileNotFoundError(
            f"SRT-файл не найден: {input_srt}"
        )

    output_srt.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    content = input_srt.read_text(
        encoding="utf-8"
    ).strip()

    if not content:
        raise RuntimeError(
            "SRT-файл пустой."
        )

    blocks = re.split(
        r"\n\s*\n",
        content,
    )

    result_blocks = []
    subtitle_number = 0

    previous_end = None

    for block in blocks:
        lines = block.splitlines()

        if len(lines) < 3:
            continue

        timing = lines[1].strip()
        text = " ".join(
            lines[2:]
        ).strip()

        if not text:
            continue

        start, end = _parse_timing(timing)

        # Убираем микроперекрытия Whisper.
        if previous_end is not None and start < previous_end:
            start = previous_end

        if end <= start:
            continue

        chunks = _split_into_chunks(text)

        if len(chunks) == 1:
            formatted = _format_two_lines(
                chunks[0]
            )

            result_blocks.append(
                _make_block(
                    subtitle_number,
                    start,
                    end,
                    formatted,
                )
            )

            subtitle_number += 1

        else:
            duration = end - start
            total_words = sum(
                len(chunk.split())
                for chunk in chunks
            )

            current_start = start

            for index, chunk in enumerate(chunks):
                word_count = len(
                    chunk.split()
                )

                if index == len(chunks) - 1:
                    current_end = end
                else:
                    chunk_duration = (
                        duration
                        * word_count
                        / total_words
                    )

                    current_end = (
                        current_start
                        + chunk_duration
                    )

                formatted = _format_two_lines(
                    chunk
                )

                result_blocks.append(
                    _make_block(
                        subtitle_number,
                        current_start,
                        current_end,
                        formatted,
                    )
                )

                subtitle_number += 1
                current_start = current_end

        previous_end = end

    if not result_blocks:
        raise RuntimeError(
            "Не удалось создать субтитры."
        )

    output_srt.write_text(
        "\n\n".join(result_blocks) + "\n",
        encoding="utf-8",
    )

    return output_srt


def _split_into_chunks(text: str) -> list[str]:
    words = text.split()

    if not words:
        return []

    chunks = []
    current = []

    for word in words:
        candidate = " ".join(
            current + [word]
        )

        if _fits_two_lines(candidate):
            current.append(word)
            continue

        if current:
            chunks.append(
                " ".join(current)
            )

        current = [word]

    if current:
        chunks.append(
            " ".join(current)
        )

    return chunks


def _fits_two_lines(text: str) -> bool:
    words = text.split()

    if len(text) <= MAX_LINE_LENGTH:
        return True

    for split in range(
        1,
        len(words),
    ):
        first = " ".join(
            words[:split]
        )

        second = " ".join(
            words[split:]
        )

        if (
            len(first) <= MAX_LINE_LENGTH
            and len(second) <= MAX_LINE_LENGTH
        ):
            return True

    return False


def _format_two_lines(text: str) -> str:
    words = text.split()

    if not words:
        return ""

    if len(text) <= MAX_LINE_LENGTH:
        return text

    best_split = None
    best_score = float("inf")

    for split in range(
        1,
        len(words),
    ):
        first = " ".join(
            words[:split]
        )

        second = " ".join(
            words[split:]
        )

        if len(first) > MAX_LINE_LENGTH:
            continue

        if len(second) > MAX_LINE_LENGTH:
            continue

        score = _split_score(
            words,
            split,
            first,
            second,
        )

        if score < best_score:
            best_score = score
            best_split = split

    if best_split is not None:
        return (
            " ".join(words[:best_split])
            + "\n"
            + " ".join(words[best_split:])
        )

    # Теоретически сюда попадём только
    # если одно отдельное слово длиннее лимита.
    return _hard_split(words)


def _split_score(
    words: list[str],
    split: int,
    first: str,
    second: str,
) -> float:

    score = abs(
        len(first) - len(second)
    )

    first_word = words[
        split - 1
    ].lower()

    second_word = words[
        split
    ].lower()

    # Не заканчиваем первую строку
    # союзом или предлогом.
    if first_word in BAD_LINE_ENDINGS:
        score += 100

    # Не начинаем вторую строку
    # с короткого союза.
    if second_word in BAD_LINE_STARTS:
        score += 60

    # Не оставляем слишком короткую
    # первую строку.
    if len(first) < 12:
        score += 30

    # Не оставляем слишком короткую
    # вторую строку.
    if len(second) < 12:
        score += 30

    return score


def _hard_split(words: list[str]) -> str:
    """
    Редкий случай:
    если нормальный перенос невозможен,
    делаем максимально сбалансированный.
    """

    best_split = 1
    best_difference = float("inf")

    for split in range(
        1,
        len(words),
    ):
        first = " ".join(
            words[:split]
        )

        second = " ".join(
            words[split:]
        )

        difference = abs(
            len(first) - len(second)
        )

        if difference < best_difference:
            best_difference = difference
            best_split = split

    return (
        " ".join(words[:best_split])
        + "\n"
        + " ".join(words[best_split:])
    )


def _parse_timing(
    timing: str,
) -> tuple[float, float]:

    start_text, end_text = timing.split(
        " --> "
    )

    return (
        _time_to_seconds(start_text),
        _time_to_seconds(end_text),
    )


def _time_to_seconds(
    value: str,
) -> float:

    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000
    )


def _seconds_to_time(
    value: float,
) -> str:

    total_ms = round(
        value * 1000
    )

    hours = total_ms // 3_600_000
    total_ms %= 3_600_000

    minutes = total_ms // 60_000
    total_ms %= 60_000

    seconds = total_ms // 1000
    milliseconds = total_ms % 1000

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d},"
        f"{milliseconds:03d}"
    )


def _make_block(
    number: int,
    start: float,
    end: float,
    text: str,
) -> str:

    return (
        f"{number}\n"
        f"{_seconds_to_time(start)} --> "
        f"{_seconds_to_time(end)}\n"
        f"{text}"
    )