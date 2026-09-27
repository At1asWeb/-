"""
Библиотека ассетов: баннеры, музыка, фоновые видео (Circle, Crop, Zoom + Crop).

Единая точка для получения списков файлов, выбора
случайного файла, поиска по имени, сохранения и удаления.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class AssetKind:
    key: str
    title: str
    directory: Path
    extensions: frozenset[str]


ASSET_KINDS: dict[str, AssetKind] = {
    "banners": AssetKind(
        key="banners",
        title="📢 Баннеры",
        directory=settings.banners_dir,
        extensions=frozenset({
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".mp4",
            ".webm",
            ".mov",
        }),
    ),
    "music": AssetKind(
        key="music",
        title="🎵 Музыка",
        directory=settings.music_dir,
        extensions=frozenset({
            ".mp3",
            ".wav",
            ".m4a",
            ".aac",
            ".ogg",
            ".flac",
        }),
    ),
    "backgrounds": AssetKind(
        key="backgrounds",
        title="🌄 Фоны",
        directory=settings.backgrounds_dir,
        extensions=frozenset({
            ".mp4",
            ".mov",
            ".mkv",
            ".webm",
        }),
    ),
    "fonts": AssetKind(
        key="fonts",
        title="🔤 Шрифты",
        directory=settings.fonts_dir,
        extensions=frozenset({
            ".ttf",
            ".otf",
        }),
    ),
}


def get_kind(kind: str) -> AssetKind:
    if kind not in ASSET_KINDS:
        raise ValueError(f"Неизвестный тип ассетов: {kind}")

    return ASSET_KINDS[kind]


def list_assets(kind: str) -> list[Path]:
    asset_kind = get_kind(kind)

    if not asset_kind.directory.exists():
        return []

    return sorted(
        (
            file
            for file in asset_kind.directory.iterdir()
            if file.is_file()
            and file.suffix.lower() in asset_kind.extensions
        ),
        key=lambda file: file.name.lower(),
    )


def random_asset(kind: str) -> Path | None:
    files = list_assets(kind)

    if not files:
        return None

    return random.choice(files)


def get_asset(kind: str, name: str) -> Path:
    """
    Возвращает файл по имени, защищаясь от выхода за пределы папки.
    """

    asset_kind = get_kind(kind)

    candidate = (asset_kind.directory / name).resolve()

    if candidate.parent != asset_kind.directory.resolve():
        raise ValueError(f"Недопустимое имя файла: {name}")

    if not candidate.is_file():
        raise FileNotFoundError(f"Файл не найден: {name}")

    if candidate.suffix.lower() not in asset_kind.extensions:
        raise ValueError(f"Неподдерживаемый формат: {candidate.suffix}")

    return candidate


def is_supported(kind: str, filename: str) -> bool:
    return Path(filename).suffix.lower() in get_kind(kind).extensions


def make_safe_destination(kind: str, original_name: str) -> Path:
    """
    Строит безопасный путь для нового файла,
    не перезаписывая существующие.
    """

    asset_kind = get_kind(kind)
    asset_kind.directory.mkdir(parents=True, exist_ok=True)

    original = Path(original_name)
    extension = original.suffix.lower()

    safe_stem = "".join(
        character
        for character in original.stem
        if character.isalnum() or character in ("_", "-")
    )[:60] or kind.rstrip("s")

    destination = asset_kind.directory / f"{safe_stem}{extension}"
    counter = 1

    while destination.exists():
        destination = (
            asset_kind.directory / f"{safe_stem}_{counter}{extension}"
        )
        counter += 1

    return destination


def delete_asset(kind: str, name: str) -> None:
    get_asset(kind, name).unlink()


def pretty_name(file: Path, limit: int = 40) -> str:
    name = file.name

    if len(name) <= limit:
        return name

    return name[: limit - 1] + "…"
