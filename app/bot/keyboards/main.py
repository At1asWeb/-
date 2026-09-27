from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def get_main_keyboard(
    is_admin: bool = False,
) -> ReplyKeyboardMarkup:

    keyboard = [
        [
            KeyboardButton(
                text="🎬 Обработать видео"
            )
        ],
        [
            KeyboardButton(
                text="🎨 Мои субтитры"
            )
        ],
        [
            KeyboardButton(
                text="ℹ️ Помощь"
            )
        ],
    ]

    if is_admin:
        keyboard.append(
            [
                KeyboardButton(
                    text="⚙️ Админ-панель"
                )
            ]
        )

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )