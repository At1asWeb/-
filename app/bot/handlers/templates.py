"""
«🎨 Мои субтитры» — личные шаблоны стиля субтитров.

Каждый пользователь создаёт свои шаблоны: шрифт, размер, положение, цвета,
обводка, тень, плашка, жирный/курсив/КАПС. Редактор — сообщение-картинка
с предпросмотром, которая перерисовывается после каждого изменения.
Шаблон выбирается при обработке видео на шаге субтитров.
"""

import asyncio
import time
from pathlib import Path

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

from app.config import settings
from app.processing.subtitle_style import (
    available_fonts,
    color_title,
    default_style,
    normalize_style,
    parse_hex_color,
)
from app.processing.subtitles import render_subtitles_preview
from app.storage import (
    MAX_TEMPLATES_PER_USER,
    SUBTITLE_COLORS,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from app.bot.keyboards.templates import (
    COLOR_TARGETS,
    FLAG_SETTINGS,
    STEP_SETTINGS,
    get_colors_keyboard,
    get_delete_confirm_keyboard,
    get_editor_keyboard,
    get_fonts_keyboard,
    get_input_cancel_keyboard,
    get_templates_list_keyboard,
)


MAX_NAME_LENGTH = 30
MAX_PREVIEW_TEXT_LENGTH = 120

# Рендер предпросмотра по очереди для каждого пользователя,
# чтобы быстрые нажатия не перемешивали картинки.
_render_locks: dict[int, asyncio.Lock] = {}


class TemplateStates(StatesGroup):
    waiting_input = State()


# ==========================================
# СПИСОК ШАБЛОНОВ
# ==========================================

def _list_text(templates: list[dict]) -> str:
    lines = [
        "🎨 Мои шаблоны субтитров",
        "",
        "Настройте свой стиль: шрифт, размер, положение, цвета, обводку, "
        "тень, плашку, жирный/курсив/КАПС — с живым предпросмотром.",
        "Шаблон выбирается при обработке видео на шаге «Субтитры».",
        "",
    ]

    if templates:
        lines.append(f"Шаблонов: {len(templates)} из {MAX_TEMPLATES_PER_USER}.")
    else:
        lines.append("Шаблонов пока нет — нажмите «➕ Новый шаблон».")

    return "\n".join(lines)


async def templates_menu_handler(message: Message, state: FSMContext):
    await state.clear()

    templates = list_templates(message.from_user.id)
    await message.answer(
        _list_text(templates),
        reply_markup=get_templates_list_keyboard(templates),
    )


async def _show_list(callback: CallbackQuery) -> None:
    templates = list_templates(callback.from_user.id)
    text = _list_text(templates)
    keyboard = get_templates_list_keyboard(templates)

    # С картинки на текст сообщение не переделать — отправляем новое.
    if callback.message.photo:
        await _safe_delete(callback.message)
        await callback.message.answer(text, reply_markup=keyboard)
    else:
        await callback.message.edit_text(text, reply_markup=keyboard)


# ==========================================
# РЕДАКТОР
# ==========================================

def _editor_caption(template: dict) -> str:
    style = template["style"]

    flags = [
        title
        for key, title in (
            ("bold", "жирный"),
            ("italic", "курсив"),
            ("uppercase", "КАПС"),
            ("box", "плашка"),
        )
        if style[key]
    ]

    return (
        f"🎨 Шаблон: {template['name']}\n\n"
        f"🔤 Шрифт: {style['font']}, размер {style['font_size']}\n"
        f"⬇️ Высота от низа: {style['bottom_offset_percent']}%, "
        f"поля по бокам: {style['margin_percent']}%\n"
        f"📏 Символов в строке: до {style['max_line_length']}\n"
        f"🎨 Текст: {color_title(style['text_color'])}, "
        f"обводка: {color_title(style['outline_color'])} "
        f"({style['outline']}), тень: {style['shadow']}\n"
        f"✨ {', '.join(flags) if flags else 'без эффектов'}\n\n"
        "Нажимайте кнопки — предпросмотр обновится.\n"
        "Жёлтые линии: поля по бокам и нижняя граница текста."
    )


async def _render(user_id: int, template: dict) -> Path:
    preview_file = (
        settings.temp_dir
        / f"tpl_{user_id}_{template['id']}_{time.monotonic_ns()}.png"
    )

    await asyncio.to_thread(
        render_subtitles_preview,
        preview_file,
        None,
        style=template["style"],
        sample_text=template.get("preview_text") or None,
    )

    return preview_file


async def _send_editor(message: Message, user_id: int, template: dict) -> Message:
    lock = _render_locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        preview_file = await _render(user_id, template)

        try:
            return await message.answer_photo(
                FSInputFile(preview_file),
                caption=_editor_caption(template),
                reply_markup=get_editor_keyboard(template),
            )
        finally:
            preview_file.unlink(missing_ok=True)


async def _refresh_editor(callback: CallbackQuery, template: dict) -> None:
    """
    Перерисовывает предпросмотр в том же сообщении.
    """

    if not callback.message.photo:
        await _safe_delete(callback.message)
        await _send_editor(callback.message, callback.from_user.id, template)
        return

    lock = _render_locks.setdefault(callback.from_user.id, asyncio.Lock())

    async with lock:
        preview_file = await _render(callback.from_user.id, template)

        try:
            await callback.message.edit_media(
                InputMediaPhoto(
                    media=FSInputFile(preview_file),
                    caption=_editor_caption(template),
                ),
                reply_markup=get_editor_keyboard(template),
            )
        except Exception as error:
            if "not modified" not in str(error):
                raise
        finally:
            preview_file.unlink(missing_ok=True)


async def _safe_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


def _set_style(user_id: int, template: dict, **changes) -> dict:
    style = normalize_style({**template["style"], **changes})
    return update_template(user_id, template["id"], style=style) or template


# ==========================================
# КНОПКИ tpl:*
# ==========================================

async def templates_callback_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    user_id = callback.from_user.id

    if action == "noop":
        await callback.answer()
        return

    if action == "close":
        await state.clear()
        await callback.answer()
        await _safe_delete(callback.message)
        return

    if action == "list":
        await state.clear()
        await callback.answer()
        await _show_list(callback)
        return

    if action == "new":
        if len(list_templates(user_id)) >= MAX_TEMPLATES_PER_USER:
            await callback.answer(
                f"Не больше {MAX_TEMPLATES_PER_USER} шаблонов. Удалите лишний.",
                show_alert=True,
            )
            return

        await callback.answer()
        await _ask_input(callback, state, "new", None, "✏️ Введите название нового шаблона:")
        return

    template_id = parts[2] if len(parts) > 2 else ""
    template = get_template(user_id, template_id)

    if template is None:
        await callback.answer("Шаблон не найден", show_alert=True)
        await _show_list(callback)
        return

    template["style"] = normalize_style(template.get("style"))

    try:
        await _template_action(callback, state, action, parts, template)
    except Exception as error:
        print(f"Ошибка редактора шаблонов: {type(error).__name__}: {error}")
        await callback.message.answer("❌ Не удалось обновить предпросмотр.")


async def _template_action(
    callback: CallbackQuery,
    state: FSMContext,
    action: str,
    parts: list[str],
    template: dict,
) -> None:
    user_id = callback.from_user.id
    template_id = template["id"]

    if action == "open":
        await state.clear()
        await callback.answer()

        # Возврат из подменю: картинка не менялась, меняем только кнопки.
        if callback.message.photo:
            await callback.message.edit_reply_markup(
                reply_markup=get_editor_keyboard(template)
            )
        else:
            await _refresh_editor(callback, template)
        return

    if action == "inc":
        code, delta = parts[3], int(parts[4])
        key = STEP_SETTINGS[code][0]
        new_value = template["style"][key] + delta
        updated = _set_style(user_id, template, **{key: new_value})

        if updated["style"][key] == template["style"][key]:
            await callback.answer("Это предельное значение")
            return

        await callback.answer()
        await _refresh_editor(callback, updated)
        return

    if action == "tog":
        key = FLAG_SETTINGS[parts[3]][0]
        updated = _set_style(user_id, template, **{key: not template["style"][key]})
        await callback.answer()
        await _refresh_editor(callback, updated)
        return

    if action == "fonts":
        await callback.answer()
        await callback.message.edit_reply_markup(
            reply_markup=get_fonts_keyboard(template, available_fonts())
        )
        return

    if action == "font":
        fonts = available_fonts()
        index = int(parts[3])

        if index >= len(fonts):
            await callback.answer("Шрифт не найден", show_alert=True)
            return

        updated = _set_style(user_id, template, font=fonts[index])
        await callback.answer(f"Шрифт: {fonts[index]}")
        await _refresh_editor(callback, updated)
        return

    if action == "colors":
        await callback.answer()
        await callback.message.edit_reply_markup(
            reply_markup=get_colors_keyboard(template, parts[3])
        )
        return

    if action == "color":
        target, color_key = parts[3], parts[4]

        if target not in COLOR_TARGETS or color_key not in SUBTITLE_COLORS:
            await callback.answer("Неизвестный цвет", show_alert=True)
            return

        updated = _set_style(user_id, template, **{COLOR_TARGETS[target][0]: color_key})
        await callback.answer()
        await _refresh_editor(callback, updated)
        return

    if action == "hex":
        target = parts[3]

        if target not in COLOR_TARGETS:
            await callback.answer("Неизвестный цвет", show_alert=True)
            return

        await callback.answer()
        await _ask_input(
            callback,
            state,
            f"hex_{target}",
            template_id,
            f"🎨 {COLOR_TARGETS[target][1]}: отправьте цвет в формате HEX, "
            "например #FFD400.\n\nПодобрать цвет: google «color picker».",
        )
        return

    if action == "text":
        await callback.answer()
        await _ask_input(
            callback,
            state,
            "text",
            template_id,
            "💬 Отправьте текст для предпросмотра "
            f"(до {MAX_PREVIEW_TEXT_LENGTH} символов).\n"
            "Он нужен только для примера и не попадает в видео.\n"
            "Отправьте «-», чтобы вернуть стандартный текст.",
        )
        return

    if action == "name":
        await callback.answer()
        await _ask_input(callback, state, "name", template_id, "✏️ Введите новое название шаблона:")
        return

    if action == "dup":
        try:
            copy = create_template(
                user_id,
                f"{template['name']} (копия)"[:MAX_NAME_LENGTH],
                dict(template["style"]),
            )
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

        copy = update_template(
            user_id, copy["id"], preview_text=template.get("preview_text", "")
        ) or copy

        await callback.answer("Копия создана")
        await _safe_delete(callback.message)
        await _send_editor(callback.message, user_id, copy)
        return

    if action == "del":
        await callback.answer()
        await callback.message.edit_reply_markup(
            reply_markup=get_delete_confirm_keyboard(template_id)
        )
        return

    if action == "delok":
        delete_template(user_id, template_id)
        await callback.answer("Шаблон удалён")
        await _show_list(callback)
        return

    if action == "cancel":
        await state.clear()
        await callback.answer("Отменено")
        await _safe_delete(callback.message)
        return

    await callback.answer("Неизвестное действие")


# ==========================================
# ВВОД ТЕКСТА (название, HEX, текст примера)
# ==========================================

async def _ask_input(
    callback: CallbackQuery,
    state: FSMContext,
    field: str,
    template_id: str | None,
    prompt: str,
) -> None:
    await state.set_state(TemplateStates.waiting_input)
    await state.update_data(
        tpl_field=field,
        tpl_id=template_id,
        # Сообщение редактора удалим после ввода и пришлём свежее ниже.
        tpl_editor_message_id=callback.message.message_id if template_id else None,
    )

    await callback.message.answer(
        prompt,
        reply_markup=get_input_cancel_keyboard(template_id or "none"),
    )


async def template_input_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("tpl_field")
    template_id = data.get("tpl_id")
    user_id = message.from_user.id
    text = " ".join((message.text or "").split())

    if field == "new":
        name = text[:MAX_NAME_LENGTH]

        if not name:
            await message.answer("Название не может быть пустым. Попробуйте ещё раз.")
            return

        try:
            template = create_template(user_id, name, default_style())
        except ValueError as error:
            await state.clear()
            await message.answer(f"❌ {error}")
            return

        await state.clear()
        await message.answer(
            "✅ Шаблон создан на основе стандартного стиля. Настройте его:"
        )
        await _send_editor(message, user_id, template)
        return

    template = get_template(user_id, template_id) if template_id else None

    if template is None:
        await state.clear()
        await message.answer("Шаблон не найден. Откройте «🎨 Мои субтитры» заново.")
        return

    template["style"] = normalize_style(template.get("style"))

    if field == "name":
        if not text:
            await message.answer("Название не может быть пустым. Попробуйте ещё раз.")
            return

        template = update_template(user_id, template_id, name=text[:MAX_NAME_LENGTH]) or template

    elif field == "text":
        preview_text = "" if text == "-" else text[:MAX_PREVIEW_TEXT_LENGTH]
        template = update_template(user_id, template_id, preview_text=preview_text) or template

    elif field in ("hex_t", "hex_o"):
        color = parse_hex_color(text)

        if color is None:
            await message.answer(
                "❌ Не понял цвет. Нужен формат #RRGGBB, например #FFD400."
            )
            return

        key = COLOR_TARGETS[field[-1]][0]
        template = _set_style(user_id, template, **{key: color})

    else:
        await state.clear()
        return

    await state.clear()

    editor_message_id = data.get("tpl_editor_message_id")

    if editor_message_id:
        try:
            await message.bot.delete_message(message.chat.id, editor_message_id)
        except Exception:
            pass

    try:
        await _send_editor(message, user_id, template)
    except Exception as error:
        print(f"Ошибка предпросмотра шаблона: {type(error).__name__}: {error}")
        await message.answer("❌ Не удалось построить предпросмотр.")

