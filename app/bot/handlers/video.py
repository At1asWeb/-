"""
Сценарий обработки видео:

ссылка → режим уникализации → зеркало → субтитры → баннер →
картинка в конце (если она загружена) → очередь → результат.

При выборе «субтитры с проверкой текста» речь распознаётся заранее,
пользователь правит текст в чате, и только потом видео рендерится.

Пакетный режим: несколько ссылок одним сообщением (через «;», запятую,
пробел или с новой строки) или .txt-файлом. Настройки выбираются один раз,
видео обрабатываются по очереди. Ручная правка субтитров в пакете недоступна.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import settings
from app.cleanup.cleanup import cleanup_task
from app.processing.downloader import DownloadError, download_video
from app.processing.library import list_assets
from app.processing.lock import is_processing, processing_slot, queue_size
from app.processing.media import FFmpegError
from app.processing.outro import OUTRO_DURATION, find_outro_image
from app.processing.processor import (
    MODES,
    NO_SPEECH_NOTE,
    ProcessingOptions,
    prepare_subtitles,
    process_video,
)
from app.processing.subtitle_editor import (
    SubtitleBlock,
    apply_edits,
    editing_messages,
    read_srt_blocks,
    write_edited_srt,
)
from app.storage import record_processing
from app.bot.keyboards.processing import (
    get_banners_keyboard,
    get_batch_stop_keyboard,
    get_mirror_keyboard,
    get_modes_keyboard,
    get_outro_keyboard,
    get_subtitles_edit_keyboard,
    get_subtitles_keyboard,
)


URL_PATTERN = re.compile(
    r"https?://(?:www\.|m\.)?"
    r"(?:youtube\.com/(?:shorts/|watch\?v=)|youtu\.be/)"
    # «;» и «,» — разделители в списке ссылок, не часть адреса.
    r"[\w\-]{6,}[^\s;,]*",
    re.IGNORECASE,
)

# Список ссылок файлом: .txt до 1 МБ.
BATCH_FILE_MAX_BYTES = 1024 * 1024
BATCH_FILE_EXTENSIONS = (".txt", ".csv", ".list")

# Пользователи, у которых прямо сейчас идёт задача.
_active_users: set[int] = set()

# Сколько ждать правки субтитров, после чего обработка продолжается
# с текущим текстом.
SUBTITLE_EDIT_TIMEOUT_SECONDS = 30 * 60


class JobCancelled(Exception):
    pass


@dataclass
class SubtitleEditSession:
    blocks: list[SubtitleBlock]
    done: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False


# Открытые сессии правки субтитров: user_id → сессия.
_edit_sessions: dict[int, SubtitleEditSession] = {}

# Запущенные пакеты: user_id → флаг «остановить после текущего видео».
_batch_stops: dict[int, asyncio.Event] = {}


class VideoStates(StatesGroup):
    waiting_for_url = State()
    choosing_mode = State()
    choosing_mirror = State()
    choosing_subtitles = State()
    choosing_banner = State()
    choosing_outro = State()
    editing_subtitles = State()


def extract_url(text: str | None) -> str | None:
    match = URL_PATTERN.search(text or "")
    return match.group(0) if match else None


def extract_urls(text: str | None) -> list[str]:
    """
    Все ссылки из текста в исходном порядке, без повторов.
    """

    return list(dict.fromkeys(URL_PATTERN.findall(text or "")))


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
        "📋 Можно сразу несколько: списком через «;», запятую или "
        "с новой строки, либо .txt-файлом со ссылками — "
        f"до {settings.max_batch_size} шт. за раз. "
        "Настройки выберете один раз, видео обработаются по очереди.\n\n"
        "Для отмены — /cancel"
    )


async def video_url_handler(message: Message, state: FSMContext):
    await _accept_urls(message, state, extract_urls(message.text))


async def batch_file_handler(message: Message, state: FSMContext):
    document = message.document
    name = (document.file_name or "").lower()

    if not name.endswith(BATCH_FILE_EXTENSIONS):
        await message.answer(
            "❌ Нужен текстовый файл (.txt) со ссылками на YouTube Shorts."
        )
        return

    if document.file_size and document.file_size > BATCH_FILE_MAX_BYTES:
        await message.answer("❌ Файл слишком большой (максимум 1 МБ).")
        return

    try:
        buffer = await message.bot.download(document)
        raw = buffer.read()
    except Exception as error:
        print(f"Не удалось скачать список ссылок: {error}")
        await message.answer("❌ Не удалось прочитать файл. Попробуйте ещё раз.")
        return

    # Блокнот Windows может сохранить файл в cp1251.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")

    await _accept_urls(message, state, extract_urls(text))


async def _accept_urls(message: Message, state: FSMContext, urls: list[str]) -> None:
    if not urls:
        await message.answer(
            "❌ Не нашёл ссылок на YouTube.\n\n"
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

    skipped = 0

    if len(urls) > settings.max_batch_size:
        skipped = len(urls) - settings.max_batch_size
        urls = urls[: settings.max_batch_size]

    await state.clear()
    await state.update_data(source_url=urls[0], source_urls=urls)
    await state.set_state(VideoStates.choosing_mode)

    if len(urls) == 1:
        accepted = "🔗 Ссылка принята."
    else:
        accepted = f"📋 Принято ссылок: {len(urls)}. Обработаю их по очереди."

        if skipped:
            accepted += (
                f"\n⚠️ Лишние {skipped} пропущены "
                f"(максимум {settings.max_batch_size} за раз)."
            )

    await message.answer(
        f"{accepted}\n\n"
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

    if extract_urls(message.text):
        await video_url_handler(message, state)
        return

    await message.answer(
        "Не понял команду 🤔\n\n"
        "Нажмите «🎬 Обработать видео» или просто отправьте "
        "ссылку на YouTube Shorts."
    )


async def cancel_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    _cancel_edit_session(user_id)

    if _stop_batch(user_id):
        await state.clear()
        await message.answer(
            "⏹ Пакет будет остановлен после текущего видео."
        )
        return

    await state.clear()
    await message.answer("✖️ Действие отменено.")


def _stop_batch(user_id: int | None) -> bool:
    stop = _batch_stops.get(user_id) if user_id is not None else None

    if stop is None:
        return False

    stop.set()
    return True


async def batch_stop_callback(callback: CallbackQuery, state: FSMContext):
    if _stop_batch(callback.from_user.id):
        await callback.answer("Остановлю после текущего видео")
    else:
        await callback.answer("Пакет уже завершён", show_alert=True)


async def cancel_job_callback(callback: CallbackQuery, state: FSMContext):
    _cancel_edit_session(callback.from_user.id)
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.edit_text("✖️ Обработка отменена.")


def _cancel_edit_session(user_id: int | None) -> None:
    session = _edit_sessions.get(user_id) if user_id is not None else None

    if session is not None:
        session.cancelled = True
        session.done.set()


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
    is_batch = len(data.get("source_urls") or []) > 1
    batch_note = (
        "\n\nВ пакетном режиме субтитры добавляются автоматически, "
        "без ручной проверки текста."
        if is_batch
        else ""
    )

    await callback.message.edit_text(
        f"Режим: {MODES[data['mode']]}\n"
        f"Зеркало: {'да' if mirror else 'нет'}\n\n"
        f"📝 Добавить субтитры?{batch_note}",
        reply_markup=get_subtitles_keyboard(allow_edit=not is_batch),
    )


# ==========================================
# ШАГ 4. СУБТИТРЫ
# ==========================================

async def subtitles_handler(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":", 1)[1]
    subtitles = choice in ("yes", "edit")
    data = await state.get_data()
    # В пакете ручной правки нет, даже если прилетела старая кнопка.
    edit_subtitles = choice == "edit" and len(data.get("source_urls") or []) <= 1

    banner_names = [file.name for file in list_assets("banners")]

    await state.update_data(
        subtitles=subtitles,
        edit_subtitles=edit_subtitles,
        banner_names=banner_names,
    )
    await state.set_state(VideoStates.choosing_banner)
    await callback.answer()

    data = await state.get_data()

    await callback.message.edit_text(
        f"Режим: {MODES[data['mode']]}\n"
        f"Зеркало: {'да' if data.get('mirror', True) else 'нет'}\n"
        f"Субтитры: {_subtitles_label(subtitles, edit_subtitles)}\n\n"
        "📢 Выберите рекламный баннер:",
        reply_markup=get_banners_keyboard(banner_names),
    )


def _subtitles_label(subtitles: bool, edit_subtitles: bool) -> str:
    if not subtitles:
        return "нет"

    return "да, с проверкой текста" if edit_subtitles else "да"


# ==========================================
# ШАГ 5. БАННЕР
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

    await state.update_data(banner_name=banner_name)

    # Шаг с концовкой показываем, только если картинка загружена.
    if find_outro_image() is None:
        await _start_job(callback, state, outro=False)
        return

    await state.set_state(VideoStates.choosing_outro)
    await callback.answer()

    await callback.message.edit_text(
        f"Режим: {MODES[mode]}\n"
        f"Зеркало: {'да' if data.get('mirror', True) else 'нет'}\n"
        f"Субтитры: "
        f"{_subtitles_label(bool(data.get('subtitles')), bool(data.get('edit_subtitles')))}\n"
        f"Баннер: {banner_name or 'без рекламы'}\n\n"
        f"🖼 Добавить картинку в конце видео ({OUTRO_DURATION:.0f} сек)?\n\n"
        "Зеркало, субтитры и баннер на неё не накладываются.",
        reply_markup=get_outro_keyboard(),
    )


# ==========================================
# ШАГ 6. КАРТИНКА В КОНЦЕ → ЗАПУСК
# ==========================================

async def outro_handler(callback: CallbackQuery, state: FSMContext):
    outro = callback.data.split(":", 1)[1] == "yes"
    await _start_job(callback, state, outro=outro)


async def _start_job(
    callback: CallbackQuery,
    state: FSMContext,
    outro: bool,
) -> None:
    data = await state.get_data()

    url = data.get("source_url")
    urls = data.get("source_urls") or ([url] if url else [])
    mode = data.get("mode")
    banner_name = data.get("banner_name")

    if not urls or mode not in MODES:
        await state.clear()
        await callback.answer()
        await callback.message.edit_text(
            "❌ Данные сессии потеряны. Отправьте ссылку заново."
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
        outro=outro,
    )
    is_batch = len(urls) > 1
    edit_subtitles = (
        options.subtitles and not is_batch and bool(data.get("edit_subtitles"))
    )

    await state.clear()
    await callback.answer()

    summary = (
        f"Режим: {MODES[mode]}\n"
        f"Зеркало: {'да' if options.mirror else 'нет'}\n"
        f"Субтитры: {_subtitles_label(options.subtitles, edit_subtitles)}\n"
        f"Баннер: {banner_name or 'без рекламы'}\n"
        f"Картинка в конце: {'да' if outro else 'нет'}"
    )

    _active_users.add(user_id)

    if is_batch:
        status = await callback.message.edit_text(
            f"📋 Пакет: {len(urls)} видео\n\n{summary}\n\n🚀 Запускаю…",
            reply_markup=get_batch_stop_keyboard(),
        )

        asyncio.create_task(
            run_batch(
                status_message=status if isinstance(status, Message) else callback.message,
                chat_id=callback.message.chat.id,
                user_id=user_id,
                urls=urls,
                options=options,
                summary=summary,
            )
        )
        return

    status = await callback.message.edit_text(f"{summary}\n\n🚀 Запускаю…")

    asyncio.create_task(
        run_job(
            status_message=status if isinstance(status, Message) else callback.message,
            chat_id=callback.message.chat.id,
            user_id=user_id,
            url=url,
            options=options,
            summary=summary,
            state=state,
            edit_subtitles=edit_subtitles,
        )
    )


# ==========================================
# РУЧНАЯ ПРАВКА СУБТИТРОВ
# ==========================================

EDIT_INSTRUCTIONS = (
    "✏️ <b>Проверьте текст субтитров</b>\n\n"
    "Ниже — распознанные фразы с номерами. Чтобы исправить, "
    "отправьте сообщением строки в том же формате:\n"
    "<code>3. исправленный текст</code>\n\n"
    "• можно прислать только изменённые строки или весь список целиком;\n"
    "• можно отправлять несколько сообщений подряд;\n"
    "• чтобы удалить фразу, оставьте после номера пустоту: <code>3.</code>\n"
    "• тайминги сохраняются, переносы строк расставятся сами.\n\n"
    "Когда закончите — нажмите «✅ Готово»."
)


async def _edit_subtitles(
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: FSMContext,
    srt_file: Path,
    work_dir: Path,
) -> Path | None:
    """
    Показывает текст субтитров и ждёт правок. Возвращает итоговый SRT
    или None, если пользователь удалил все фразы.
    """

    session = SubtitleEditSession(blocks=read_srt_blocks(srt_file))

    if not session.blocks:
        return None

    _edit_sessions[user_id] = session
    await state.set_state(VideoStates.editing_subtitles)

    try:
        await bot.send_message(chat_id, EDIT_INSTRUCTIONS, parse_mode="HTML")

        for part in editing_messages(session.blocks):
            await bot.send_message(chat_id, part)

        await bot.send_message(
            chat_id,
            "Жду правки или нажмите «✅ Готово», если всё верно.",
            reply_markup=get_subtitles_edit_keyboard(),
        )

        try:
            await asyncio.wait_for(
                session.done.wait(),
                timeout=SUBTITLE_EDIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await bot.send_message(
                chat_id,
                "⏰ Время на правку вышло — продолжаю с текущим текстом.",
            )

    finally:
        _edit_sessions.pop(user_id, None)

        if await state.get_state() == VideoStates.editing_subtitles.state:
            await state.clear()

    if session.cancelled:
        raise JobCancelled()

    return await asyncio.to_thread(write_edited_srt, session.blocks, work_dir)


async def subtitles_edit_message_handler(message: Message, state: FSMContext):
    session = _edit_sessions.get(message.from_user.id)

    if session is None:
        await state.clear()
        await message.answer("Сессия правки субтитров уже закрыта.")
        return

    result = apply_edits(session.blocks, message.text or "")

    lines = []

    if result.changed:
        lines.append(f"✏️ Исправлено: {', '.join(map(str, result.changed))}")

    if result.deleted:
        lines.append(f"🗑 Удалено: {', '.join(map(str, result.deleted))}")

    if result.invalid:
        preview = "\n".join(result.invalid[:5])
        lines.append(
            "⚠️ Не понял строки (нужен формат «номер. текст», "
            f"номера от 1 до {len(session.blocks)}):\n{preview}"
        )

    if not lines:
        lines.append("Изменений нет — текст совпадает с текущим.")

    lines.append("\nМожно прислать ещё правки или нажать «✅ Готово».")

    await message.answer(
        "\n".join(lines),
        reply_markup=get_subtitles_edit_keyboard(),
    )


async def subtitles_edit_done_callback(callback: CallbackQuery, state: FSMContext):
    session = _edit_sessions.get(callback.from_user.id)

    if session is None:
        await callback.answer("Правка уже завершена", show_alert=True)
        return

    session.done.set()
    await callback.answer("Принято")
    await callback.message.edit_text("✅ Текст субтитров принят, продолжаю обработку.")


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
    state: FSMContext | None = None,
    edit_subtitles: bool = False,
    job_suffix: str = "",
    release_user: bool = True,
) -> bool:
    """
    Обрабатывает одно видео. Возвращает True, если результат отправлен.
    """

    job_id = f"u{user_id}_{int(time.time())}{job_suffix}"
    input_dir = settings.input_dir / job_id
    work_dir = settings.output_dir / job_id

    status = StatusUpdater(status_message, summary)
    started = time.monotonic()
    success = False
    cancelled = False
    error_text = None
    extra_notes: list[str] = []

    try:
        await status.set("⬇️ Скачиваю видео…")

        source = await asyncio.to_thread(download_video, url, input_dir)

        if edit_subtitles and state is not None:
            if is_processing():
                await status.set(
                    f"⏳ Видео в очереди. Задач перед вами: {queue_size() + 1}"
                )

            # Слот нужен только на распознавание: пока пользователь
            # правит текст, очередь обрабатывает другие видео.
            async with processing_slot():
                await status.set("📝 Распознаю речь для субтитров…")
                srt_file = await asyncio.to_thread(
                    prepare_subtitles, source, work_dir
                )

            if srt_file is not None:
                await status.set("✏️ Жду проверки текста субтитров (сообщения ниже)…")
                srt_file = await _edit_subtitles(
                    bot=status_message.bot,
                    chat_id=chat_id,
                    user_id=user_id,
                    state=state,
                    srt_file=srt_file,
                    work_dir=work_dir,
                )

                if srt_file is None:
                    extra_notes.append("ℹ️ Все фразы удалены — субтитры не добавлены.")
            else:
                extra_notes.append(NO_SPEECH_NOTE)

            options = (
                replace(options, subtitles_file=srt_file)
                if srt_file is not None
                else replace(options, subtitles=False)
            )

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
            f"Картинка в конце: {'да' if result.outro_added else 'нет'}",
            f"Размер: {result.size_mb:.2f} MB",
        ]

        notes = extra_notes + result.notes

        if notes:
            caption_lines += ["", *notes]

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

    except JobCancelled:
        cancelled = True
        await status.set("✖️ Обработка отменена.")

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
        if release_user:
            _active_users.discard(user_id)

        await asyncio.to_thread(cleanup_task, input_dir, work_dir)

        if not cancelled:
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

    return success


# ==========================================
# ПАКЕТНАЯ ОБРАБОТКА
# ==========================================

async def run_batch(
    status_message: Message,
    chat_id: int,
    user_id: int,
    urls: list[str],
    options: ProcessingOptions,
    summary: str,
) -> None:
    """
    Обрабатывает ссылки по очереди с одинаковыми настройками.
    Ошибка одного видео не останавливает остальные.
    """

    bot = status_message.bot
    stop = asyncio.Event()
    _batch_stops[user_id] = stop

    total = len(urls)
    failed: list[int] = []
    done = 0

    async def set_status(text: str, keyboard=None) -> None:
        try:
            await status_message.edit_text(
                f"📋 Пакет: {total} видео\n\n{summary}\n\n{text}",
                reply_markup=keyboard,
            )
        except Exception as error:
            if "not modified" not in str(error):
                print(f"Не удалось обновить статус пакета: {error}")

    try:
        for index, url in enumerate(urls, start=1):
            if stop.is_set():
                break

            await set_status(
                f"▶️ Видео {index} из {total}\n"
                f"Готово: {done - len(failed)}, с ошибкой: {len(failed)}",
                get_batch_stop_keyboard(),
            )

            job_header = f"🎬 Видео {index}/{total}\n{url}"

            try:
                job_message = await bot.send_message(
                    chat_id,
                    f"{job_header}\n\n⏳ Ожидание…",
                    disable_web_page_preview=True,
                )

                success = await run_job(
                    status_message=job_message,
                    chat_id=chat_id,
                    user_id=user_id,
                    url=url,
                    options=options,
                    summary=job_header,
                    job_suffix=f"_{index}",
                    release_user=False,
                )
            except Exception as error:
                print(f"Ошибка пакета (видео {index}): {type(error).__name__}: {error}")
                success = False

            done += 1

            if not success:
                failed.append(index)

    finally:
        _batch_stops.pop(user_id, None)
        _active_users.discard(user_id)

    succeeded = done - len(failed)
    lines = [f"✅ Пакет завершён: {succeeded} из {total} видео готово."]

    if failed:
        lines.append(f"❌ С ошибкой: {', '.join(map(str, failed))}")

    if done < total:
        lines.append(f"⏹ Остановлено вручную, не обработано: {total - done}")

    await set_status("\n".join(lines))

    try:
        await bot.send_message(chat_id, "\n".join(lines))
    except Exception as error:
        print(f"Не удалось отправить итог пакета: {error}")
