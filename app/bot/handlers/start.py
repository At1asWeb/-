from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.config import settings
from app.bot.keyboards.main import get_main_keyboard


async def start_handler(message: Message, state: FSMContext):
    if not message.from_user:
        return

    await state.clear()

    is_admin = message.from_user.id in settings.admin_ids

    await message.answer(
        "Привет! 👋\n\n"
        "Это Shorts Processor — бот для уникализации YouTube Shorts.\n\n"
        "Нажмите «🎬 Обработать видео» или просто отправьте ссылку.",
        reply_markup=get_main_keyboard(is_admin=is_admin),
    )


async def help_handler(message: Message):
    await message.answer(
        "ℹ️ Помощь\n\n"
        "1. Отправьте ссылку на YouTube Shorts.\n"
        "2. Выберите вид уникализации:\n"
        "   ⭕ Circle — видео в круге на анимированном фоне;\n"
        "   🔍 Zoom +15% — увеличение кадра на 15%;\n"
        "   ✂️ Crop 15% — обрезка сверху и снизу по 15%, "
        "видео на анимированном фоне;\n"
        "   🔍✂️ Zoom + Crop 15% — приближение на 15%, затем обрезка "
        "сверху и снизу по 15%, видео на анимированном фоне.\n"
        "3. Решите, нужно ли отзеркаливание.\n"
        "4. Решите, нужны ли субтитры.\n"
        "5. Выберите баннер или «Без рекламы».\n\n"
        "🎨 «Мои субтитры» — свои шаблоны стиля субтитров (шрифт, цвет, "
        "обводка, размер, положение) с предпросмотром. Шаблон выбирается "
        "на шаге «Субтитры».\n\n"
        "📋 Несколько видео сразу: отправьте ссылки одним сообщением "
        "(через «;», запятую или с новой строки) или .txt-файлом. "
        "Настройки выбираются один раз, видео обрабатываются по очереди. "
        "Ручная правка субтитров в этом режиме недоступна.\n\n"
        "Порядок обработки:\n"
        "уникализация → отзеркаливание (если выбрано) → субтитры → баннер.\n"
        "Субтитры и баннер накладываются после зеркала, "
        "поэтому текст читается нормально.\n\n"
        f"Максимальная длина видео: {settings.max_video_duration} сек.\n\n"
        "/cancel — отменить текущее действие."
    )
