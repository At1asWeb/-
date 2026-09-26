from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.processing.library import ASSET_KINDS, pretty_name


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(ASSET_KINDS["banners"].title, "adm:assets:banners"),
                _button(ASSET_KINDS["music"].title, "adm:assets:music"),
            ],
            [
                _button(ASSET_KINDS["backgrounds"].title, "adm:assets:backgrounds"),
            ],
            [
                _button("📊 Статистика", "adm:stats"),
                _button("⚙️ Настройки", "adm:settings"),
            ],
            [
                _button("🧹 Очистить временные файлы", "adm:cleanup"),
            ],
        ]
    )


def get_asset_section_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("➕ Добавить", f"adm:add:{kind}")],
            [_button("🗑 Удалить", f"adm:del:{kind}")],
            [_button("◀️ Назад", "adm:main")],
        ]
    )


def get_asset_delete_keyboard(kind: str, names: list[str]) -> InlineKeyboardMarkup:
    from pathlib import Path

    rows = [
        [
            _button(
                f"❌ {pretty_name(Path(name), 45)}",
                f"adm:rm:{kind}:{index}",
            )
        ]
        for index, name in enumerate(names)
    ]

    rows.append([_button("◀️ Назад", f"adm:assets:{kind}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_delete_confirm_keyboard(kind: str, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("✅ Да, удалить", f"adm:rmok:{kind}:{index}"),
                _button("✖️ Нет", f"adm:del:{kind}"),
            ]
        ]
    )


def get_cancel_upload_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("✖️ Отмена", f"adm:assets:{kind}")]]
    )


def get_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("🔄 Обновить", "adm:stats")],
            [_button("♻️ Сбросить статистику", "adm:stats_reset")],
            [_button("◀️ Назад", "adm:main")],
        ]
    )


def get_stats_reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("✅ Да, сбросить", "adm:stats_reset_ok"),
                _button("✖️ Нет", "adm:stats"),
            ]
        ]
    )


BANNER_FIT_TITLES = {
    "fit": "вписать",
    "crop": "заполнить",
    "stretch": "растянуть",
}


def get_settings_keyboard(runtime: dict) -> InlineKeyboardMarkup:
    music_state = "✅ вкл" if runtime["music_enabled"] else "❌ выкл"

    height = runtime["banner_height_percent"]
    height_title = f"Высота баннера {height}%" if height else "Высота баннера: авто"

    rows = [
        [_button(f"🎵 Фоновая музыка: {music_state}", "adm:set:music_toggle")],
        [
            _button("➖", "adm:set:music_volume_percent:-1"),
            _button(f"Громкость {runtime['music_volume_percent']:g}%", "adm:noop"),
            _button("➕", "adm:set:music_volume_percent:1"),
        ],
        [
            _button("➖", "adm:set:banner_width_percent:-5"),
            _button(
                # В авто-режиме ширина = пропорциональный размер баннера.
                f"{'Размер' if not height else 'Ширина'} баннера "
                f"{runtime['banner_width_percent']}%",
                "adm:noop",
            ),
            _button("➕", "adm:set:banner_width_percent:5"),
        ],
        [
            _button("➖", "adm:set:banner_height_percent:-1"),
            _button(height_title, "adm:noop"),
            _button("➕", "adm:set:banner_height_percent:1"),
        ],
    ]

    if height:
        rows.append(
            [
                _button(
                    f"Вписывание: {BANNER_FIT_TITLES.get(runtime['banner_fit'], 'вписать')}",
                    "adm:set:fit_cycle",
                ),
                _button("Высота: авто", "adm:set:height_auto"),
            ]
        )

    rows += [
        [
            _button("➖", "adm:set:banner_top_offset_percent:-2"),
            _button(
                f"Отступ сверху {runtime['banner_top_offset_percent']}%",
                "adm:noop",
            ),
            _button("➕", "adm:set:banner_top_offset_percent:2"),
        ],
        [
            _button("➖", "adm:set:banner_opacity:-0.05"),
            _button(
                f"Непрозрачность {runtime['banner_opacity'] * 100:.0f}%",
                "adm:noop",
            ),
            _button("➕", "adm:set:banner_opacity:0.05"),
        ],
        [_button("👁 Предпросмотр баннера", "adm:preview")],
        [_button("↩️ Сбросить к значениям из .env", "adm:set:reset")],
        [_button("◀️ Назад", "adm:main")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_preview_keyboard(banner_names: list[str]) -> InlineKeyboardMarkup:
    from pathlib import Path

    rows = [
        [
            _button(
                f"👁 {pretty_name(Path(name), 45)}",
                f"adm:pv:{index}",
            )
        ]
        for index, name in enumerate(banner_names)
    ]

    rows.append([_button("◀️ Назад", "adm:settings")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
