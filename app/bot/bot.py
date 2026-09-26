import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.cleanup.cleanup import cleanup_old_files

from app.bot.handlers.start import help_handler, start_handler

from app.bot.handlers.video import (
    VideoStates,
    banner_handler,
    cancel_handler,
    cancel_job_callback,
    mirror_handler,
    mode_handler,
    outro_handler,
    process_video_start,
    subtitles_handler,
    text_fallback_handler,
    video_url_handler,
)

from app.bot.handlers.admin import (
    AssetUploadState,
    admin_callback_handler,
    admin_panel_handler,
    asset_upload_handler,
    cancel_upload_command,
)


def build_proxy_url() -> str | None:
    """
    Формирует SOCKS5 URL из настроек .env.
    """

    if not settings.proxy_enabled:
        return None

    if not settings.proxy_host or not settings.proxy_port:
        return None

    if settings.proxy_username and settings.proxy_password:
        return (
            f"socks5://"
            f"{settings.proxy_username}:"
            f"{settings.proxy_password}@"
            f"{settings.proxy_host}:"
            f"{settings.proxy_port}"
        )

    return f"socks5://{settings.proxy_host}:{settings.proxy_port}"


def create_bot() -> Bot:
    # Большой таймаут нужен для отправки видео.
    proxy_url = build_proxy_url()

    if proxy_url:
        print("SOCKS5 прокси: включён")
        session = AiohttpSession(proxy=proxy_url, timeout=600)
    else:
        print("SOCKS5 прокси: выключен")
        session = AiohttpSession(timeout=600)

    return Bot(token=settings.bot_token, session=session)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # ------------------------------------------
    # Команды (работают в любом состоянии)
    # ------------------------------------------

    dp.message.register(start_handler, CommandStart())
    dp.message.register(
        cancel_upload_command,
        Command("cancel"),
        StateFilter(AssetUploadState.waiting_for_file),
    )
    dp.message.register(cancel_handler, Command("cancel"))
    dp.message.register(help_handler, Command("help"))
    dp.message.register(admin_panel_handler, Command("admin"))

    # ------------------------------------------
    # Главное меню
    # ------------------------------------------

    dp.message.register(help_handler, F.text == "ℹ️ Помощь")
    dp.message.register(process_video_start, F.text == "🎬 Обработать видео")
    dp.message.register(admin_panel_handler, F.text == "⚙️ Админ-панель")

    # ------------------------------------------
    # Загрузка файлов в админке (до общих текстовых хендлеров)
    # ------------------------------------------

    dp.message.register(
        asset_upload_handler,
        StateFilter(AssetUploadState.waiting_for_file),
    )

    # ------------------------------------------
    # Сценарий обработки видео
    # ------------------------------------------

    dp.message.register(
        video_url_handler,
        StateFilter(VideoStates.waiting_for_url),
        F.text,
    )

    dp.callback_query.register(
        mode_handler,
        StateFilter(VideoStates.choosing_mode),
        F.data.startswith("mode:"),
    )
    dp.callback_query.register(
        mirror_handler,
        StateFilter(VideoStates.choosing_mirror),
        F.data.startswith("mirror:"),
    )
    dp.callback_query.register(
        subtitles_handler,
        StateFilter(VideoStates.choosing_subtitles),
        F.data.startswith("subtitles:"),
    )
    dp.callback_query.register(
        banner_handler,
        StateFilter(VideoStates.choosing_banner),
        F.data.startswith("banner:"),
    )
    dp.callback_query.register(
        outro_handler,
        StateFilter(VideoStates.choosing_outro),
        F.data.startswith("outro:"),
    )
    dp.callback_query.register(cancel_job_callback, F.data == "job:cancel")

    # ------------------------------------------
    # Админ-панель
    # ------------------------------------------

    dp.callback_query.register(admin_callback_handler, F.data.startswith("adm:"))

    # ------------------------------------------
    # Устаревшие кнопки (после перезапуска бота состояние теряется)
    # ------------------------------------------

    dp.callback_query.register(_stale_callback)

    # ------------------------------------------
    # Любой другой текст: ссылка → обработка, иначе подсказка
    # ------------------------------------------

    dp.message.register(text_fallback_handler, F.text)

    return dp


async def _stale_callback(callback):
    await callback.answer(
        "Эта кнопка устарела. Начните заново: 🎬 Обработать видео",
        show_alert=True,
    )


async def _periodic_cleanup() -> None:
    while True:
        try:
            removed = await asyncio.to_thread(cleanup_old_files)

            if removed:
                print(f"Автоочистка: удалено старых объектов: {removed}")

        except Exception as error:
            print(f"Ошибка автоочистки: {error}")

        await asyncio.sleep(3600)


async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не указан в файле .env")

    for directory in (
        settings.input_dir,
        settings.temp_dir,
        settings.output_dir,
        settings.data_dir,
        settings.banners_dir,
        settings.music_dir,
        settings.backgrounds_dir,
        settings.outro_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    bot = create_bot()
    dp = create_dispatcher()

    cleanup_task = asyncio.create_task(_periodic_cleanup())

    print("=== BOT START ===")

    try:
        await dp.start_polling(bot)
    finally:
        cleanup_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
