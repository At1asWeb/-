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


def get_subtitles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, добавить",
                    callback_data="subtitles:yes",
                ),
                InlineKeyboardButton(
                    text="❌ Без субтитров",
                    callback_data="subtitles:no",
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
                    text="🖼 Да, добавить",
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
