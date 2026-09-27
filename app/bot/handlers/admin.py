"""
Админ-панель:

- 📢 Баннеры / 🎵 Музыка / 🌄 Фоны — список, добавление, удаление;
- 📊 Статистика обработок;
- ⚙️ Настройки (музыка, громкость, геометрия и прозрачность баннера);
- 📝 Субтитры (размер, положение, цвета) с предпросмотром;
- 🧹 Очистка временных файлов.
"""

import asyncio
from pathlib import Path

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import settings
from app.cleanup.cleanup import cleanup_old_files
from app.processing.banner import render_banner_preview
from app.processing.library import (
    get_kind,
    is_supported,
    list_assets,
    make_safe_destination,
)
from app.processing.lock import is_processing, queue_size
from app.processing.media import get_duration, get_video_size, probe
from app.processing.subtitle_style import read_font_family
from app.processing.subtitles import render_subtitles_preview
from app.storage import (
    BANNER_FIT_MODES,
    BANNER_HEIGHT_AUTO_BELOW,
    SUBTITLE_COLORS,
    SUBTITLE_SETTING_KEYS,
    get_runtime,
    get_stats,
    reset_runtime,
    reset_stats,
    update_runtime,
)
from app.bot.handlers.video import has_active_jobs
from app.bot.keyboards.admin import (
    BANNER_FIT_TITLES,
    get_admin_keyboard,
    get_asset_delete_keyboard,
    get_asset_section_keyboard,
    get_cancel_upload_keyboard,
    get_delete_confirm_keyboard,
    get_preview_keyboard,
    get_settings_keyboard,
    get_stats_keyboard,
    get_stats_reset_confirm_keyboard,
    get_subtitle_settings_keyboard,
)


# Лимит Telegram Bot API на скачивание файлов ботом.
TELEGRAM_DOWNLOAD_LIMIT_MB = 20


class AssetUploadState(StatesGroup):
    waiting_for_file = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


MAIN_TEXT = "⚙️ Админ-панель\n\nВыберите раздел:"


# ==========================================
# ВХОД В ПАНЕЛЬ
# ==========================================

async def admin_panel_handler(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return

    await state.clear()
    await message.answer(MAIN_TEXT, reply_markup=get_admin_keyboard())


# ==========================================
# ОБРАБОТЧИК ВСЕХ КНОПОК adm:*
# ==========================================

async def admin_callback_handler(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "noop":
        await callback.answer()
        return

    if action == "main":
        await state.clear()
        await callback.answer()
        await _edit(callback, MAIN_TEXT, get_admin_keyboard())
        return

    if action == "assets":
        await state.clear()
        await callback.answer()
        await _show_asset_section(callback, parts[2])
        return

    if action == "add":
        await _start_upload(callback, state, parts[2])
        return

    if action == "del":
        await callback.answer()
        await _show_delete_list(callback, parts[2])
        return

    if action == "rm":
        await callback.answer()
        await _confirm_delete(callback, parts[2], int(parts[3]))
        return

    if action == "rmok":
        await _delete_asset(callback, parts[2], int(parts[3]))
        return

    if action == "stats":
        await callback.answer()
        await _edit(callback, _stats_text(), get_stats_keyboard())
        return

    if action == "stats_reset":
        await callback.answer()
        await _edit(
            callback,
            "♻️ Сбросить всю статистику?",
            get_stats_reset_confirm_keyboard(),
        )
        return

    if action == "stats_reset_ok":
        reset_stats()
        await callback.answer("Статистика сброшена")
        await _edit(callback, _stats_text(), get_stats_keyboard())
        return

    if action == "settings":
        await callback.answer()
        await _show_settings(callback)
        return

    if action == "set":
        await _change_setting(callback, parts[2:])
        return

    if action == "preview":
        await _show_preview_list(callback)
        return

    if action == "pv":
        await _send_preview(callback, int(parts[2]))
        return

    if action == "subs":
        await callback.answer()
        await _show_subtitle_settings(callback)
        return

    if action == "subset":
        await _change_subtitle_setting(callback, parts[2], parts[3])
        return

    if action == "subcolor":
        await _cycle_subtitle_color(callback, parts[2])
        return

    if action == "subreset":
        reset_runtime(SUBTITLE_SETTING_KEYS)
        await callback.answer("Настройки субтитров сброшены")
        await _show_subtitle_settings(callback)
        return

    if action == "subpv":
        await _send_subtitles_preview(callback, None)
        return

    if action == "subpvlist":
        await _show_subtitles_preview_list(callback)
        return

    if action == "subpvb":
        await _send_subtitles_preview(callback, int(parts[2]))
        return

    if action == "cleanup":
        await _cleanup(callback)
        return

    await callback.answer("Неизвестное действие")


async def _edit(callback: CallbackQuery, text: str, keyboard) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as error:
        # "message is not modified" и т.п. — не критично.
        if "not modified" not in str(error):
            print(f"Ошибка редактирования сообщения: {error}")


# ==========================================
# БИБЛИОТЕКА АССЕТОВ
# ==========================================

def _asset_list_text(kind: str) -> str:
    asset_kind = get_kind(kind)
    files = list_assets(kind)

    lines = [asset_kind.title, ""]

    if not files:
        lines.append("Файлов пока нет.")
    else:
        total_mb = 0.0

        for index, file in enumerate(files, start=1):
            size_mb = file.stat().st_size / 1024 / 1024
            total_mb += size_mb
            lines.append(f"{index}. {file.name} — {size_mb:.2f} MB")

        lines += ["", f"Всего: {len(files)} ({total_mb:.1f} MB)"]

    if kind == "backgrounds" and not files:
        lines += ["", "⚠️ Без фонов режимы Circle, Crop и Zoom + Crop работать не будут."]

    if kind == "music" and not files:
        lines += ["", "Без музыки видео будет только с оригинальным звуком."]

    return "\n".join(lines)


async def _show_asset_section(callback: CallbackQuery, kind: str) -> None:
    await _edit(callback, _asset_list_text(kind), get_asset_section_keyboard(kind))


async def _start_upload(callback: CallbackQuery, state: FSMContext, kind: str) -> None:
    asset_kind = get_kind(kind)

    await state.set_state(AssetUploadState.waiting_for_file)
    await state.update_data(upload_kind=kind)
    await callback.answer()

    formats = ", ".join(
        sorted(extension.lstrip(".").upper() for extension in asset_kind.extensions)
    )

    hint = {
        "banners": "Картинку можно отправить как фото. Видео/GIF — файлом.",
        "music": "Отправьте трек как аудио или файлом.",
        "backgrounds": "Лучше всего вертикальное видео 1080x1920 без звука.",
        "fonts": "Отправьте файл шрифта (TTF/OTF). Для русского текста "
        "шрифт должен поддерживать кириллицу.",
    }[kind]

    await _edit(
        callback,
        f"➕ Добавление: {asset_kind.title}\n\n"
        f"Отправьте файл одним сообщением.\n{hint}\n\n"
        f"Форматы: {formats}\n"
        f"Максимальный размер: {TELEGRAM_DOWNLOAD_LIMIT_MB} MB "
        "(ограничение Telegram).\n"
        "Файлы больше можно положить вручную в папку "
        f"assets/{asset_kind.directory.name}.",
        get_cancel_upload_keyboard(kind),
    )


async def asset_upload_handler(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    kind = data.get("upload_kind")

    if kind is None:
        await state.clear()
        return

    asset_kind = get_kind(kind)

    # ------------------------------------------
    # Определяем файл из сообщения
    # ------------------------------------------

    file_id = None
    file_size = 0
    original_name = None

    if message.document:
        file_id = message.document.file_id
        file_size = message.document.file_size or 0
        original_name = message.document.file_name or "file"

    elif message.photo and kind == "banners":
        photo = message.photo[-1]
        file_id = photo.file_id
        file_size = photo.file_size or 0
        original_name = "banner.jpg"

    elif message.video:
        file_id = message.video.file_id
        file_size = message.video.file_size or 0
        original_name = message.video.file_name or f"{kind}.mp4"

    elif message.animation and kind == "banners":
        file_id = message.animation.file_id
        file_size = message.animation.file_size or 0
        original_name = message.animation.file_name or "banner.mp4"

    elif message.audio and kind == "music":
        file_id = message.audio.file_id
        file_size = message.audio.file_size or 0
        original_name = message.audio.file_name or "track.mp3"

    if file_id is None:
        await message.answer(
            "❌ Не вижу подходящего файла.\n"
            "Отправьте файл или нажмите «✖️ Отмена».",
            reply_markup=get_cancel_upload_keyboard(kind),
        )
        return

    if not is_supported(kind, original_name):
        await message.answer(
            f"❌ Формат {Path(original_name).suffix or '(без расширения)'} "
            "не поддерживается для этого раздела.",
            reply_markup=get_cancel_upload_keyboard(kind),
        )
        return

    if file_size > TELEGRAM_DOWNLOAD_LIMIT_MB * 1024 * 1024:
        await message.answer(
            f"❌ Файл больше {TELEGRAM_DOWNLOAD_LIMIT_MB} MB — Telegram "
            "не позволяет боту его скачать.\n"
            f"Положите файл вручную в папку assets/{asset_kind.directory.name}.",
            reply_markup=get_cancel_upload_keyboard(kind),
        )
        return

    destination = make_safe_destination(kind, original_name)

    # ------------------------------------------
    # Скачиваем
    # ------------------------------------------

    try:
        telegram_file = await message.bot.get_file(file_id)
        await message.bot.download_file(
            telegram_file.file_path,
            destination=destination,
        )

    except Exception as error:
        print(f"Ошибка загрузки файла: {type(error).__name__}: {error}")
        destination.unlink(missing_ok=True)

        await message.answer(
            "❌ Не удалось скачать файл. Попробуйте ещё раз.",
            reply_markup=get_cancel_upload_keyboard(kind),
        )
        return

    # ------------------------------------------
    # Проверяем, что FFmpeg умеет его читать
    # ------------------------------------------

    try:
        details = await asyncio.to_thread(_validate_media, kind, destination)

    except Exception as error:
        print(f"Файл не прошёл проверку: {error}")
        destination.unlink(missing_ok=True)

        await message.answer(
            "❌ Файл повреждён или не является медиафайлом нужного типа.",
            reply_markup=get_cancel_upload_keyboard(kind),
        )
        return

    await state.clear()

    size_mb = destination.stat().st_size / 1024 / 1024

    await message.answer(
        f"✅ Файл добавлен!\n\n"
        f"📁 {destination.name}\n"
        f"📦 {size_mb:.2f} MB\n"
        f"{details}"
    )

    await message.answer(
        _asset_list_text(kind),
        reply_markup=get_asset_section_keyboard(kind),
    )


def _validate_media(kind: str, file: Path) -> str:
    if kind == "fonts":
        family = read_font_family(file)

        if not family:
            raise RuntimeError("Не удалось прочитать имя шрифта")

        return f"🔤 Семейство: {family} (доступно в «🎨 Мои субтитры»)"

    if kind == "music":
        info = probe(file)

        if not any(
            stream.get("codec_type") == "audio"
            for stream in info.get("streams", [])
        ):
            raise RuntimeError("Нет аудиопотока")

        return f"⏱ {get_duration(file):.0f} сек"

    width, height = get_video_size(file)
    return f"🖼 {width}x{height}"


async def _show_delete_list(callback: CallbackQuery, kind: str) -> None:
    files = list_assets(kind)

    if not files:
        await _edit(
            callback,
            f"{_asset_list_text(kind)}\n\nУдалять нечего.",
            get_asset_section_keyboard(kind),
        )
        return

    await _edit(
        callback,
        f"🗑 Удаление: {get_kind(kind).title}\n\nВыберите файл:",
        get_asset_delete_keyboard(kind, [file.name for file in files]),
    )


async def _confirm_delete(callback: CallbackQuery, kind: str, index: int) -> None:
    files = list_assets(kind)

    if index >= len(files):
        await _show_delete_list(callback, kind)
        return

    await _edit(
        callback,
        f"Удалить файл?\n\n📁 {files[index].name}",
        get_delete_confirm_keyboard(kind, index),
    )


async def _delete_asset(callback: CallbackQuery, kind: str, index: int) -> None:
    files = list_assets(kind)

    if index >= len(files):
        await callback.answer("Файл уже удалён", show_alert=True)
        await _show_delete_list(callback, kind)
        return

    if is_processing() or has_active_jobs():
        await callback.answer(
            "Сейчас идёт обработка видео. Удалите файл чуть позже.",
            show_alert=True,
        )
        return

    file = files[index]

    try:
        file.unlink()
    except OSError as error:
        await callback.answer(f"Не удалось удалить: {error}", show_alert=True)
        return

    await callback.answer(f"Удалено: {file.name}")
    await _show_asset_section(callback, kind)


async def cancel_upload_command(message: Message, state: FSMContext):
    data = await state.get_data()
    kind = data.get("upload_kind", "banners")

    await state.clear()
    await message.answer(
        "✖️ Загрузка отменена.",
        reply_markup=get_asset_section_keyboard(kind),
    )


# ==========================================
# СТАТИСТИКА
# ==========================================

def _stats_text() -> str:
    stats = get_stats()

    total = stats["total"]
    success = stats["success"]

    average = stats["processing_seconds"] / success if success else 0

    lines = [
        "📊 Статистика",
        "",
        f"Всего запусков: {total}",
        f"✅ Успешно: {success}",
        f"❌ С ошибкой: {stats['failed']}",
        f"👤 Пользователей: {len(stats['users'])}",
        f"⏱ Среднее время: {average:.0f} сек",
        "",
        "По режимам:",
    ]

    from app.processing.processor import MODES

    for key, title in MODES.items():
        lines.append(f"  {title}: {stats['by_mode'].get(key, 0)}")

    lines += [
        "",
        f"📝 С субтитрами: {stats['with_subtitles']}",
        f"📢 С баннером: {stats['with_banner']}",
    ]

    by_day = sorted(stats["by_day"].items(), reverse=True)[:7]

    if by_day:
        lines += ["", "Последние дни:"]
        lines += [f"  {day}: {count}" for day, count in by_day]

    lines += [
        "",
        f"Сейчас в работе: {'да' if is_processing() else 'нет'}",
        f"В очереди: {queue_size()}",
    ]

    if stats["last_run"]:
        lines.append(f"Последний запуск: {stats['last_run']}")

    if stats["last_error"]:
        lines += [
            "",
            f"Последняя ошибка ({stats['last_error']['time']}):",
            stats["last_error"]["text"],
        ]

    return "\n".join(lines)


# ==========================================
# НАСТРОЙКИ
# ==========================================

def _settings_text(runtime: dict) -> str:
    height = runtime["banner_height_percent"]

    if height:
        fit_title = BANNER_FIT_TITLES.get(runtime["banner_fit"], "вписать")
        height_line = (
            f"↕️ Высота баннера: {height}% высоты видео\n"
            f"🧩 Вписывание: {fit_title}\n"
        )
    else:
        height_line = (
            "↕️ Высота баннера: авто (по пропорциям)\n"
            "💡 Кнопки «Размер баннера» ➖/➕ уменьшают и увеличивают "
            "баннер целиком, без обрезки и искажений.\n"
        )

    return (
        "⚙️ Настройки\n\n"
        "Изменения применяются к следующим обработкам.\n\n"
        f"🎵 Фоновая музыка: {'включена' if runtime['music_enabled'] else 'выключена'}\n"
        f"🔊 Громкость музыки: {runtime['music_volume_percent']:g}%\n\n"
        f"↔️ Ширина баннера: {runtime['banner_width_percent']}% ширины видео\n"
        f"{height_line}"
        f"⬇️ Отступ баннера сверху: {runtime['banner_top_offset_percent']}% высоты\n"
        f"👁 Непрозрачность баннера: {runtime['banner_opacity'] * 100:.0f}%\n\n"
        "Вписывание (когда высота задана вручную):\n"
        "• вписать — баннер целиком, без искажений;\n"
        "• заполнить — заполняет область, края обрезаются;\n"
        "• растянуть — точно под размер, возможны искажения.\n\n"
        "Проверить, как выглядит, — «👁 Предпросмотр баннера»."
    )


async def _show_settings(callback: CallbackQuery) -> None:
    runtime = get_runtime()
    await _edit(callback, _settings_text(runtime), get_settings_keyboard(runtime))


def _current_auto_height_percent(width_percent: int) -> int:
    """
    Какую высоту (в %) сейчас имеет первый баннер в авто-режиме.
    Используется как стартовое значение при переходе на ручную высоту.
    """

    banners = list_assets("banners")

    if not banners:
        return 15

    try:
        banner_width, banner_height = get_video_size(banners[0])
    except Exception:
        return 15

    height_px = 1080 * width_percent / 100 * banner_height / banner_width
    return max(BANNER_HEIGHT_AUTO_BELOW, min(50, round(height_px / 1920 * 100)))


async def _change_setting(callback: CallbackQuery, arguments: list[str]) -> None:
    runtime = get_runtime()
    action = arguments[0]

    if action == "reset":
        # Настройки субтитров сбрасываются отдельной кнопкой в своём разделе.
        reset_runtime(
            tuple(key for key in runtime if key not in SUBTITLE_SETTING_KEYS)
        )
        await callback.answer("Настройки сброшены")

    elif action == "music_toggle":
        update_runtime(music_enabled=not runtime["music_enabled"])
        await callback.answer()

    elif action == "fit_cycle":
        current = runtime["banner_fit"]
        index = BANNER_FIT_MODES.index(current) if current in BANNER_FIT_MODES else 0
        new_fit = BANNER_FIT_MODES[(index + 1) % len(BANNER_FIT_MODES)]

        update_runtime(banner_fit=new_fit)
        await callback.answer(f"Вписывание: {BANNER_FIT_TITLES[new_fit]}")

    elif action == "height_auto":
        update_runtime(banner_height_percent=0)
        await callback.answer("Высота: авто")

    elif action == "banner_height_percent" and runtime["banner_height_percent"] == 0:
        # Из «авто» стартуем с текущей реальной высоты баннера,
        # чтобы кнопки ➖/➕ меняли её плавно, а не скачком.
        try:
            delta = int(float(arguments[1]))
        except (IndexError, ValueError):
            await callback.answer("Неизвестная настройка", show_alert=True)
            return

        if delta < 0:
            await callback.answer("Высота уже в режиме «авто»")
            return

        start = await asyncio.to_thread(
            _current_auto_height_percent,
            runtime["banner_width_percent"],
        )
        update_runtime(banner_height_percent=start)
        await callback.answer(f"Высота баннера: {start}%")

    else:
        try:
            delta = float(arguments[1])
            update_runtime(**{action: runtime[action] + delta})
        except (KeyError, IndexError, ValueError):
            await callback.answer("Неизвестная настройка", show_alert=True)
            return

        await callback.answer()

    await _show_settings(callback)


# ==========================================
# ПРЕДПРОСМОТР БАННЕРА
# ==========================================

async def _show_preview_list(callback: CallbackQuery) -> None:
    banners = list_assets("banners")

    if not banners:
        await callback.answer("Баннеров нет. Добавьте их в разделе «Баннеры».", show_alert=True)
        return

    await callback.answer()
    await _edit(
        callback,
        "👁 Предпросмотр баннера\n\n"
        "Выберите баннер — пришлю кадр 1080x1920 с текущими настройками.",
        get_preview_keyboard([file.name for file in banners]),
    )


async def _send_preview(callback: CallbackQuery, index: int) -> None:
    banners = list_assets("banners")

    if index >= len(banners):
        await callback.answer("Баннер не найден", show_alert=True)
        return

    await callback.answer("Готовлю предпросмотр…")

    banner = banners[index]
    preview_file = settings.temp_dir / f"preview_{callback.from_user.id}.png"

    try:
        _, geometry = await asyncio.to_thread(
            render_banner_preview,
            banner,
            preview_file,
        )

        runtime = get_runtime()

        caption = (
            f"👁 {banner.name}\n\n"
            f"Размер на видео 1080x1920: "
            f"{geometry['width']}x{geometry['height']} px\n"
            f"Занимает {geometry['height'] / 1920 * 100:.0f}% высоты кадра\n"
            f"Позиция: x={geometry['x']}, y={geometry['y']}"
        )

        if runtime["banner_height_percent"]:
            caption += "\n\nЖёлтая рамка — заданная область баннера."

        await callback.message.answer_photo(
            FSInputFile(preview_file),
            caption=caption,
        )

    except Exception as error:
        print(f"Ошибка предпросмотра: {type(error).__name__}: {error}")
        await callback.message.answer("❌ Не удалось построить предпросмотр.")

    finally:
        preview_file.unlink(missing_ok=True)

    runtime = get_runtime()
    await callback.message.answer(
        _settings_text(runtime),
        reply_markup=get_settings_keyboard(runtime),
    )


# ==========================================
# НАСТРОЙКИ СУБТИТРОВ
# ==========================================

def _subtitle_settings_text(runtime: dict) -> str:
    return (
        "📝 Настройки субтитров\n\n"
        "Изменения применяются к следующим обработкам. "
        "Значения указаны для кадра 1080x1920 и масштабируются под видео.\n\n"
        f"🔠 Размер шрифта: {runtime['subtitle_font_size']}\n"
        f"⬇️ Отступ снизу: {runtime['subtitle_bottom_offset_percent']}% высоты\n"
        f"↔️ Поля по бокам: {runtime['subtitle_margin_percent']}% ширины\n"
        f"📏 Символов в строке: до {runtime['subtitle_max_line_length']} "
        "(не больше 2 строк на фразу)\n"
        f"🖌 Толщина обводки: {runtime['subtitle_outline']}\n"
        f"🎨 Цвет текста: {SUBTITLE_COLORS[runtime['subtitle_text_color']][0]}\n"
        f"🎨 Цвет обводки: {SUBTITLE_COLORS[runtime['subtitle_outline_color']][0]}\n\n"
        "Проверить, как выглядит, — «👁 Предпросмотр». "
        "«С баннером» покажет, не пересекаются ли субтитры с рекламой."
    )


async def _show_subtitle_settings(callback: CallbackQuery) -> None:
    runtime = get_runtime()
    await _edit(
        callback,
        _subtitle_settings_text(runtime),
        get_subtitle_settings_keyboard(runtime),
    )


async def _change_subtitle_setting(
    callback: CallbackQuery,
    key: str,
    delta_text: str,
) -> None:
    runtime = get_runtime()

    try:
        if key not in SUBTITLE_SETTING_KEYS:
            raise KeyError(key)

        update_runtime(**{key: runtime[key] + int(delta_text)})
    except (KeyError, ValueError):
        await callback.answer("Неизвестная настройка", show_alert=True)
        return

    await callback.answer()
    await _show_subtitle_settings(callback)


async def _cycle_subtitle_color(callback: CallbackQuery, key: str) -> None:
    runtime = get_runtime()

    if key not in SUBTITLE_SETTING_KEYS or key not in runtime:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return

    colors = list(SUBTITLE_COLORS)
    current = runtime[key]
    index = colors.index(current) if current in colors else 0
    new_color = colors[(index + 1) % len(colors)]

    update_runtime(**{key: new_color})
    await callback.answer(f"Цвет: {SUBTITLE_COLORS[new_color][0]}")
    await _show_subtitle_settings(callback)


async def _show_subtitles_preview_list(callback: CallbackQuery) -> None:
    banners = list_assets("banners")

    if not banners:
        await callback.answer("Баннеров нет. Добавьте их в разделе «Баннеры».", show_alert=True)
        return

    await callback.answer()
    await _edit(
        callback,
        "👁 Предпросмотр субтитров с баннером\n\n"
        "Выберите баннер — пришлю кадр 1080x1920 с текущими настройками.",
        get_preview_keyboard(
            [file.name for file in banners],
            prefix="adm:subpvb",
            back="adm:subs",
        ),
    )


async def _send_subtitles_preview(
    callback: CallbackQuery,
    banner_index: int | None,
) -> None:
    banner = None

    if banner_index is not None:
        banners = list_assets("banners")

        if banner_index >= len(banners):
            await callback.answer("Баннер не найден", show_alert=True)
            return

        banner = banners[banner_index]

    await callback.answer("Готовлю предпросмотр…")

    preview_file = settings.temp_dir / f"subtitles_preview_{callback.from_user.id}.png"

    try:
        await asyncio.to_thread(render_subtitles_preview, preview_file, banner)

        caption = (
            "👁 Предпросмотр субтитров\n\n"
            "Жёлтые линии: рамка — поля по бокам, "
            "горизонтальная линия — нижняя граница текста.\n\n"
            "Если строка не помещается в рамку, она переносится на следующую. "
            "Фраза длиннее 2 строк показывается частями — здесь первая."
        )

        if banner is not None:
            caption += f"\nБаннер: {banner.name}"

        await callback.message.answer_photo(FSInputFile(preview_file), caption=caption)

    except Exception as error:
        print(f"Ошибка предпросмотра субтитров: {type(error).__name__}: {error}")
        await callback.message.answer("❌ Не удалось построить предпросмотр.")

    finally:
        preview_file.unlink(missing_ok=True)

    runtime = get_runtime()
    await callback.message.answer(
        _subtitle_settings_text(runtime),
        reply_markup=get_subtitle_settings_keyboard(runtime),
    )


# ==========================================
# ОЧИСТКА
# ==========================================

async def _cleanup(callback: CallbackQuery) -> None:
    if is_processing() or has_active_jobs():
        await callback.answer(
            "Сейчас идёт обработка. Попробуйте позже.",
            show_alert=True,
        )
        return

    removed = await asyncio.to_thread(cleanup_old_files, 0)

    await callback.answer(f"Удалено объектов: {removed}", show_alert=True)
