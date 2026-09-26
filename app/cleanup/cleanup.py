import shutil
import time
from pathlib import Path

from app.config import settings


def remove_directory(directory: Path) -> None:
    """
    Полностью удаляет указанную папку, если она существует.
    """

    if not directory.exists():
        return

    if not directory.is_dir():
        raise ValueError(f"Ожидалась папка, но получен файл: {directory}")

    shutil.rmtree(directory, ignore_errors=True)


def cleanup_task(*directories: Path) -> None:
    """
    Удаляет рабочие папки текущей задачи.
    """

    for directory in directories:
        try:
            remove_directory(directory)
        except Exception as error:
            print(f"Ошибка очистки {directory}: {type(error).__name__}: {error}")


def cleanup_old_files(max_age_hours: int | None = None) -> int:
    """
    Удаляет из work/input, work/temp, work/output всё,
    что старше TEMP_FILE_MAX_AGE_HOURS. Возвращает количество
    удалённых объектов.
    """

    if max_age_hours is None:
        max_age_hours = settings.temp_file_max_age_hours

    border = time.time() - max_age_hours * 3600
    removed = 0

    for root in (settings.input_dir, settings.temp_dir, settings.output_dir):
        if not root.exists():
            continue

        for item in root.iterdir():
            if item.name == ".gitkeep":
                continue

            try:
                if item.stat().st_mtime >= border:
                    continue

                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)

                removed += 1

            except OSError as error:
                print(f"Не удалось удалить {item}: {error}")

    return removed
