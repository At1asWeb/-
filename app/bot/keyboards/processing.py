from pathlib import Path

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.processing.library import pretty_name
from app.processing.processor import MODES


CANCEL_BUTTON = InlineKeyboardButton(
    text="✖️ Отмена",
    callback_data="job:cancel",
)


def get_modes_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *[
                [InlineKeyboardButton(text=title, callback_data=f"mode:{key}")]
                for key, title in MODES.items()
            ],
            [CANCEL_BUTTON],
        ]
    )


def get_mirror_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪞 Да, отзеркалить",
                    callback_data="mirror:yes",
                ),
                InlineKeyboardButton(
                    text="➡️ Нет, оставить как есть",
                    callback_data="mirror:no",
                ),
            ],
            [CANCEL_BUTTON],
        ]
    )


def get_subtitles_keyboard(allow_edit: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Да, автоматически",
                callback_data="subtitles:yes",
            ),
        ],
    ]

    if allow_edit:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Да, с проверкой текста",
                    callback_data="subtitles:edit",
                ),
            ]
        )

    rows += [
        [
            InlineKeyboardButton(
                text="❌ Без субтитров",
                callback_data="subtitles:no",
            ),
        ],
        [CANCEL_BUTTON],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_batch_stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏹ Остановить после текущего видео",
                    callback_data="batch:stop",
                ),
            ],
        ]
    )


def get_subtitles_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Готово — наложить субтитры",
                    callback_data="subedit:done",
                ),
            ],
            [CANCEL_BUTTON],
        ]
    )


def get_banners_keyboard(banner_names: list[str]) -> InlineKeyboardMarkup:
    """
    В callback_data передаётся индекс баннера, а не имя файла:
    имя может превышать лимит Telegram в 64 байта.
    """

    rows = [
        [InlineKeyboardButton(text="🚫 Без рекламы", callback_data="banner:none")]
    ]

    for index, name in enumerate(banner_names):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📢 {pretty_name(Path(name))}",
                    callback_data=f"banner:{index}",
                )
            ]
        )

    rows.append([CANCEL_BUTTON])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_outro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼 Да, вставить",
                    callback_data="outro:yes",
                ),
                InlineKeyboardButton(
                    text="❌ Без картинки",
                    callback_data="outro:no",
                ),
            ],
            [CANCEL_BUTTON],
        ]
    )


def get_outro_mode_keyboard(append_seconds: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"➕ В конец видео ({append_seconds:g} сек)",
                    callback_data="outromode:append",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔲 Поверх конца видео",
                    callback_data="outromode:overlay",
                ),
            ],
            [CANCEL_BUTTON],
        ]
    )


OVERLAY_SECONDS_PRESETS = (1, 2, 3, 4, 5, 7, 10)


def get_outro_seconds_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{seconds} сек", callback_data=f"outrosec:{seconds}")
        for seconds in OVERLAY_SECONDS_PRESETS
    ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons[:4],
            buttons[4:],
            [
                InlineKeyboardButton(
                    text="✏️ Своё значение",
                    callback_data="outrosec:custom",
                ),
            ],
            [CANCEL_BUTTON],
        ]
    )


def get_outro_seconds_confirm_keyboard(seconds: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Наложить на {seconds:g} сек и запустить",
                    callback_data=f"outrosec:{seconds:g}",
                ),
            ],
            [CANCEL_BUTTON],
        ]
    )
