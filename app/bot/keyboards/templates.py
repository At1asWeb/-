"""
Клавиатуры редактора шаблонов субтитров («🎨 Мои субтитры»).

callback_data: tpl:<действие>:<id шаблона>[:аргументы] — не длиннее 64 байт.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.processing.subtitle_style import color_title
from app.storage import MAX_TEMPLATES_PER_USER, SUBTITLE_COLORS


# Короткие коды настроек для callback_data: код -> (ключ стиля, шаг, подпись).
STEP_SETTINGS: dict[str, tuple[str, int, str]] = {
    "fs": ("font_size", 4, "Размер"),
    "bo": ("bottom_offset_percent", 2, "Высота"),
    "mg": ("margin_percent", 1, "Поля"),
    "ml": ("max_line_length", 2, "Символов"),
    "ol": ("outline", 1, "Обводка"),
    "sh": ("shadow", 1, "Тень"),
}

STEP_SUFFIX = {"bo": "%", "mg": "%"}

FLAG_SETTINGS: dict[str, tuple[str, str]] = {
    "b": ("bold", "Жирный"),
    "i": ("italic", "Курсив"),
    "u": ("uppercase", "КАПС"),
    "x": ("box", "Плашка"),
}

COLOR_TARGETS: dict[str, tuple[str, str]] = {
    "t": ("text_color", "Цвет текста"),
    "o": ("outline_color", "Цвет обводки / плашки"),
}


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def get_templates_list_keyboard(templates: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [_button(f"📝 {template['name']}", f"tpl:open:{template['id']}")]
        for template in templates
    ]

    if len(templates) < MAX_TEMPLATES_PER_USER:
        rows.append([_button("➕ Новый шаблон", "tpl:new")])

    rows.append([_button("✖️ Закрыть", "tpl:close")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_editor_keyboard(template: dict) -> InlineKeyboardMarkup:
    template_id = template["id"]
    style = template["style"]

    rows = [
        [_button(f"🔤 Шрифт: {style['font']}", f"tpl:fonts:{template_id}")],
    ]

    for code, (key, step, title) in STEP_SETTINGS.items():
        rows.append(
            [
                _button("➖", f"tpl:inc:{template_id}:{code}:{-step}"),
                _button(
                    f"{title} {style[key]}{STEP_SUFFIX.get(code, '')}",
                    "tpl:noop",
                ),
                _button("➕", f"tpl:inc:{template_id}:{code}:{step}"),
            ]
        )

    rows.append(
        [
            _button(
                f"🎨 Текст: {color_title(style['text_color'])}",
                f"tpl:colors:{template_id}:t",
            ),
            _button(
                f"🖌 Обводка: {color_title(style['outline_color'])}",
                f"tpl:colors:{template_id}:o",
            ),
        ]
    )

    rows.append(
        [
            _button(
                f"{'✅' if style[key] else '▫️'} {title}",
                f"tpl:tog:{template_id}:{code}",
            )
            for code, (key, title) in FLAG_SETTINGS.items()
        ]
    )

    rows += [
        [
            _button("💬 Текст примера", f"tpl:text:{template_id}"),
            _button("✏️ Название", f"tpl:name:{template_id}"),
        ],
        [
            _button("📄 Копия", f"tpl:dup:{template_id}"),
            _button("🗑 Удалить", f"tpl:del:{template_id}"),
        ],
        [_button("◀️ К списку шаблонов", "tpl:list")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_fonts_keyboard(template: dict, fonts: list[str]) -> InlineKeyboardMarkup:
    current = template["style"]["font"]

    rows = []
    row: list[InlineKeyboardButton] = []

    for index, font in enumerate(fonts):
        mark = "✅ " if font == current else ""
        row.append(_button(f"{mark}{font}", f"tpl:font:{template['id']}:{index}"))

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([_button("◀️ Назад", f"tpl:open:{template['id']}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_colors_keyboard(template: dict, target: str) -> InlineKeyboardMarkup:
    key = COLOR_TARGETS[target][0]
    current = template["style"][key]

    rows = []
    row: list[InlineKeyboardButton] = []

    for color_key, (title, _) in SUBTITLE_COLORS.items():
        mark = "✅ " if color_key == current else ""
        row.append(
            _button(f"{mark}{title}", f"tpl:color:{template['id']}:{target}:{color_key}")
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows += [
        [_button("✏️ Свой цвет (HEX)", f"tpl:hex:{template['id']}:{target}")],
        [_button("◀️ Назад", f"tpl:open:{template['id']}")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_delete_confirm_keyboard(template_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("✅ Да, удалить", f"tpl:delok:{template_id}"),
                _button("✖️ Нет", f"tpl:open:{template_id}"),
            ]
        ]
    )


def get_input_cancel_keyboard(template_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("✖️ Отмена", f"tpl:cancel:{template_id}")]]
    )


def get_subtitle_style_keyboard(templates: list[dict]) -> InlineKeyboardMarkup:
    """
    Выбор стиля субтитров при обработке видео.
    """

    rows = [[_button("⭐ Стандартный", "substyle:std")]]

    rows += [
        [_button(f"🎨 {template['name']}", f"substyle:{index}")]
        for index, template in enumerate(templates)
    ]

    rows.append([_button("✖️ Отмена", "job:cancel")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
