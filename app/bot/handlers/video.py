"""
Сценарий обработки видео:

ссылка → режим уникализации → субтитры → баннер → очередь → результат.
"""

import asyncio
import re
import time
from pathlib import Path

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import settings
from app.cleanup.cleanup import cleanup_task
from app.processing.downloader import DownloadError, download_video
from app.processing.library import list_assets
from app.processing.lock import is_processing, processing_slot, queue_size
from app.processing.media import FFmpegError
from app.processing.processor import MODES, ProcessingOptions, process_video
from app.storage import record_processing
from app.bot.keyboards.processing import (
    get_banners_keyboard,
    get_mirror_keyboard,
    get_modes_keyboard,
    get_subtitles_keyboard,
)


URL_PATTERN = re.compile(
    r"https?://(?:www\.|m\.)?"
    r"(?:youtube\.com/(?:shorts/|watch\?v=)|youtu\.be/)"
    r"[\w\-]{6,}[^\s]*",
    re.IGNORECASE,
)

# Пользователи, у которых прямо сейчас идёт задача.
_active_users: set[int] = set()


class VideoStates(StatesGroup):
    waiting_for_url = State()
    choosing_mode = State()
    choosing_mirror = State()
    choosing_subtitles = State()
    choosing_banner = State()


def extract_url(text: str | None) -> str | None:
    match = URL_PATTERN.search(text or "")
    return match.group(0) if match else None


def has_active_jobs() -> bool:
    return bool(_active_users)


# ==========================================
# ШАГ 1. ССЫЛКА
# ==========================================

async def process_video_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(VideoStates.waiting_for_url)

    await message.answer(
        "🎬 Обработка видео\n\n"
        "Отправьте ссылку на YouTube Shorts.\n\n"
        "Для отмены — /cancel"
    )


async def video_url_handler(message: Message, state: FSMContext):
    url = extract_url(message.text)

    if url is None:
        await message.answer(
            "❌ Это не похоже на ссылку YouTube.\n\n"
            "Пример: https://www.youtube.com/shorts/xxxxxxxxxxx\n\n"
            "Для отмены — /cancel"
        )
        return

    if message.from_user and message.from_user.id in _active_users:
        await message.answer(
            "⏳ Ваше предыдущее видео ещё обрабатывается.\n"
            "Дождитесь результата."
        )
        return

    await state.clear()
    await state.update_data(source_url=url)
    await state.set_state(VideoStates.choosing_mode)

    await message.answer(
        "🔗 Ссылка принята.\n\n"
        "Выберите вид уникализации:\n\n"
        "⭕ <b>Circle</b> — видео в круге на анимированном фоне\n"
        "🔍 <b>Zoom +15%</b> — увеличение кадра на 15%\n"
        "✂️ <b>Crop 15%</b> — обрезка сверху и снизу по 15%, "
        "видео на анимированном фоне\n"
        "🔍✂️ <b>Zoom + Crop 15%</b> — приближение на 15%, затем обрезка "
        "сверху и снизу по 15%, видео на анимированном фоне\n\n"
        "Во всех режимах добавляется тихая фоновая музыка. "
        "Отзеркаливание — на следующем шаге.",
        reply_markup=get_modes_keyboard(),
        parse_mode="HTML",
    )


async def text_fallback_handler(message: Message, state: FSMContext):
    """
    Сообщение вне сценария: если это ссылка — запускаем обработку.
    """

    if extract_url(message.text):
        await video_url_handler(message, state)
        return

    await message.answer(
        "Не понял команду 🤔\n\n"
        "Нажмите «🎬 Обработать видео» или просто отправьте "
        "ссылку на YouTube Shorts."
    )


async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✖️ Действие отменено.")


async def cancel_job_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.edit_text("✖️ Обработка отменена.")


# ==========================================
# ШАГ 2. РЕЖИМ
# ==========================================

async def mode_handler(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":", 1)[1]

    if mode not in MODES:
        await callback.answer("Неизвестный режим", show_alert=True)
        return

    await state.update_data(mode=mode)
    await state.set_state(VideoStates.choosing_mirror)
    await callback.answer()

    await callback.message.edit_text(
        f"Режим: {MODES[mode]}\n\n"
        "🪞 Отзеркалить видео по горизонтали?\n\n"
        "Субтитры и баннер в любом случае не зеркалятся — "
        "текст будет читаться нормально.",
        reply_markup=get_mirror_keyboard(),
    )


# ==========================================
# ШАГ 3. ОТЗЕРКАЛИВАНИЕ
# ==========================================

async def mirror_handler(callback: CallbackQuery, state: FSMContext):
    mirror = callback.data.split(":", 1)[1] == "yes"

    await state.update_data(mirror=mirror)
    await state.set_state(VideoStates.choosing_subtitles)
    await callback.answer()

    data = await state.get_data()

    await callback.message.edit_text(
        f"Режим: {MODES[data['mode']]}\n"
        f"Зеркало: {'да' if mirror else 'нет'}\n\n"
        "📝 Добавить субтитры?",
        reply_markup=get_subtitles_keyboard(),
    )


# ==========================================
# ШАГ 4. СУБТИТРЫ
# ==========================================

async def subtitles_handler(callback: CallbackQuery, state: FSMContext):
    subtitles = callback.data.split(":", 1)[1] == "yes"

    banner_names = [file.name for file in list_assets("banners")]

    await state.update_data(subtitles=subtitles, banner_names=banner_names)
    await state.set_state(VideoStates.choosing_banner)
    await callback.answer()

    data = await state.get_data()

    await callback.message.edit_text(
        f"Режим: {MODES[data['mode']]}\n"
        f"Зеркало: {'да' if data.get('mirror', True) else 'нет'}\n"
        f"Субтитры: {'да' if subtitles else 'нет'}\n\n"
        "📢 Выберите рекламный баннер:",
        reply_markup=get_banners_keyboard(banner_names),
    )


# ==========================================
# ШАГ 5. БАННЕР → ЗАПУСК
# ==========================================

async def banner_handler(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":", 1)[1]
    data = await state.get_data()

    url = data.get("source_url")
    mode = data.get("mode")

    if not url or mode not in MODES:
        await state.clear()
        await callback.answer()
        await callback.message.edit_text(
            "❌ Данные сессии потеряны. Отправьте ссылку заново."
        )
        return

    banner_name = None

    if choice != "none":
        names = data.get("banner_names", [])

        try:
            banner_name = names[int(choice)]
        except (ValueError, IndexError):
            await callback.answer("Баннер не найден", show_alert=True)
            return

        if not (settings.banners_dir / banner_name).exists():
            await callback.answer(
                "Этот баннер уже удалён. Выберите другой.",
                show_alert=True,
            )
            return

    user_id = callback.from_user.id

    if user_id in _active_users:
        await callback.answer("Ваше видео уже обрабатывается", show_alert=True)
        return

    options = ProcessingOptions(
        mode=mode,
        mirror=bool(data.get("mirror", True)),
        subtitles=bool(data.get("subtitles")),
        banner_name=banner_name,
    )

    await state.clear()
    await callback.answer()

    summary = (
        f"Режим: {MODES[mode]}\n"
        f"Зеркало: {'да' if options.mirror else 'нет'}\n"
        f"Субтитры: {'да' if options.subtitles else 'нет'}\n"
        f"Баннер: {banner_name or 'без рекламы'}"
    )

    status = await callback.message.edit_text(f"{summary}\n\n🚀 Запускаю…")

    _active_users.add(user_id)

    asyncio.create_task(
        run_job(
            status_message=status if isinstance(status, Message) else callback.message,
            chat_id=callback.message.chat.id,
            user_id=user_id,
            url=url,
            options=options,
            summary=summary,
        )
    )


# ==========================================
# ВЫПОЛНЕНИЕ ЗАДАЧИ
# ==========================================

class StatusUpdater:
    """
    Обновляет сообщение со статусом. Безопасен для вызова из потока.
    """

    def __init__(self, message: Message, header: str):
        self.message = message
        self.header = header
        self.loop = asyncio.get_running_loop()
        self.last_text = ""

    async def set(self, text: str) -> None:
        full_text = f"{self.header}\n\n{text}"

        if full_text == self.last_text:
            return

        self.last_text = full_text

        try:
            await self.message.edit_text(full_text)
        except Exception as error:
            print(f"Не удалось обновить статус: {error}")

    def from_thread(self, text: str) -> None:
        asyncio.run_coroutine_threadsafe(self.set(text), self.loop)


async def run_job(
    status_message: Message,
    chat_id: int,
    user_id: int,
    url: str,
    options: ProcessingOptions,
    summary: str,
) -> None:

    job_id = f"u{user_id}_{int(time.time())}"
    input_dir = settings.input_dir / job_id
    work_dir = settings.output_dir / job_id

    status = StatusUpdater(status_message, summary)
    started = time.monotonic()
    success = False
    error_text = None

    try:
        await status.set("⬇️ Скачиваю видео…")

        source = await asyncio.to_thread(download_video, url, input_dir)

        if is_processing():
            await status.set(
                f"⏳ Видео в очереди. Задач перед вами: {queue_size() + 1}"
            )

        async with processing_slot():
            result = await asyncio.to_thread(
                process_video,
                source,
                work_dir,
                options,
                status.from_thread,
            )

        await status.set("📤 Отправляю результат…")

        caption_lines = [
            "✅ Готово!",
            "",
            f"Режим: {MODES[result.mode]}",
            f"Зеркало: {'да' if result.mirrored else 'нет'}",
            f"Субтитры: {'да' if result.subtitles_added else 'нет'}",
            f"Баннер: {'да' if result.banner_added else 'нет'}",
            f"Размер: {result.size_mb:.2f} MB",
        ]

        if result.notes:
            caption_lines += ["", *result.notes]

        await status_message.bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(result.file, filename="shorts_result.mp4"),
            caption="\n".join(caption_lines),
            duration=int(result.duration),
            supports_streaming=True,
            request_timeout=600,
        )

        await status.set("✅ Готово! Видео отправлено ниже.")
        success = True

    except DownloadError as error:
        error_text = str(error)
        await status.set(f"❌ {error}")

    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        print(f"Ошибка обработки ({job_id}): {error_text}")

        if isinstance(error, TimeoutError):
            user_text = "Обработка заняла слишком много времени."
        elif isinstance(error, FFmpegError):
            user_text = "Ошибка при обработке видео."
        elif isinstance(error, FileNotFoundError):
            user_text = str(error)
        else:
            user_text = "Не удалось скачать или обработать видео."

        await status.set(f"❌ {user_text}\n\nПопробуйте ещё раз.")

    finally:
        _active_users.discard(user_id)

        await asyncio.to_thread(cleanup_task, input_dir, work_dir)

        try:
            record_processing(
                user_id=user_id,
                mode=options.mode,
                subtitles=options.subtitles,
                banner=options.banner_name is not None,
                success=success,
                seconds=time.monotonic() - started,
                error=error_text,
            )
        except Exception as error:
            print(f"Не удалось записать статистику: {error}")
