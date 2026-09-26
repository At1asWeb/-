"""
Ручная правка субтитров.

Пользователю показывается пронумерованный список фраз:

    1. Привет всем
    2. сегодня расскажу

Он присылает исправленные строки в том же формате («2. сегодня покажу»),
можно только изменённые. Пустая строка после номера («2.») удаляет фразу.
Тайминги не меняются, после правки текст заново разбивается на строки.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.processing.subtitle_formatter import format_srt


# Запас до лимита Telegram в 4096 символов.
MESSAGE_LIMIT = 3500

EDIT_LINE_PATTERN = re.compile(r"^\s*(\d+)\s*[.)]\s*(.*?)\s*$")


@dataclass
class SubtitleBlock:
    start: str
    end: str
    text: str


@dataclass
class EditResult:
    changed: list[int] = field(default_factory=list)
    deleted: list[int] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


def read_srt_blocks(srt_file: Path) -> list[SubtitleBlock]:
    content = srt_file.read_text(encoding="utf-8", errors="replace").strip()
    blocks: list[SubtitleBlock] = []

    for raw_block in re.split(r"\n\s*\n", content):
        lines = raw_block.strip().splitlines()

        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )

        if timing_index is None:
            continue

        start, end = (part.strip() for part in lines[timing_index].split("-->"))
        text = " ".join(line.strip() for line in lines[timing_index + 1:]).strip()

        if text:
            blocks.append(SubtitleBlock(start=start, end=end, text=text))

    return blocks


def editing_messages(blocks: list[SubtitleBlock]) -> list[str]:
    """
    Пронумерованный список фраз, разбитый на сообщения под лимит Telegram.
    """

    messages: list[str] = []
    current = ""

    for number, block in enumerate(blocks, start=1):
        line = f"{number}. {block.text}"

        if current and len(current) + len(line) + 1 > MESSAGE_LIMIT:
            messages.append(current)
            current = ""

        current = f"{current}\n{line}" if current else line

    if current:
        messages.append(current)

    return messages


def apply_edits(blocks: list[SubtitleBlock], text: str) -> EditResult:
    result = EditResult()

    for line in (text or "").splitlines():
        if not line.strip():
            continue

        match = EDIT_LINE_PATTERN.match(line)

        if match is None:
            result.invalid.append(line.strip())
            continue

        number = int(match.group(1))
        new_text = " ".join(match.group(2).split())

        if not 1 <= number <= len(blocks):
            result.invalid.append(line.strip())
            continue

        block = blocks[number - 1]

        if new_text == block.text:
            continue

        # Удалённая фраза остаётся в списке пустой, чтобы номера не сдвигались.
        block.text = new_text

        if new_text:
            result.changed.append(number)
        else:
            result.deleted.append(number)

    return result


def write_edited_srt(
    blocks: list[SubtitleBlock],
    work_dir: Path,
) -> Path | None:
    """
    Сохраняет правки и заново форматирует SRT (переносы строк,
    разбиение длинных фраз). None — если все фразы удалены.
    """

    kept = [block for block in blocks if block.text]

    if not kept:
        return None

    edited_srt = work_dir / "subtitles_edited_raw.srt"
    final_srt = work_dir / "subtitles_edited.srt"

    edited_srt.write_text(
        "\n\n".join(
            f"{number}\n{block.start} --> {block.end}\n{block.text}"
            for number, block in enumerate(kept, start=1)
        )
        + "\n",
        encoding="utf-8",
    )

    return format_srt(input_srt=edited_srt, output_srt=final_srt)
