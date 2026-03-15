# keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from storage import db


def roles_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🦸 Кузнец‑лучник", callback_data="role_info_Кузнец-лучник")],
        [InlineKeyboardButton("🛠️ Мастер", callback_data="role_info_Мастер")],
        [InlineKeyboardButton("🍳 Повар", callback_data="role_info_Повар")],
        [InlineKeyboardButton("🏹 Охотник", callback_data="role_info_Охотник")],
        [InlineKeyboardButton("💪 Работяга", callback_data="role_info_Работяга")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def role_detail_keyboard(role_name: str):
    # role_name оставил в сигнатуре — чтобы не ломать импорты/вызовы
    keyboard = [
        [InlineKeyboardButton("🔙 Назад к списку ролей", callback_data="roles_menu")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _quick_buttons_row(user_id: int):
    """
    Быстрые кнопки, которые вы хотите видеть почти везде:
    О ролях / Правила / Начать сначала / Назад.
    """
    player = db.get_player(user_id)

    # "Назад" ведём в главное меню. Это самый надёжный вариант для inline-меню.
    back_btn = InlineKeyboardButton("🔙 Назад", callback_data="menu")

    row = [
        InlineKeyboardButton("📖 О ролях", callback_data="roles_menu"),
        InlineKeyboardButton("📜 Правила", callback_data="rules_menu"),
    ]

    # "Начать сначала" показываем всем, но для совсем новых — это просто возврат к выбору роли
    row.append(InlineKeyboardButton("🔄 Начать сначала", callback_data="reset_registration"))
    row.append(back_btn)

    return row, player


def main_menu_keyboard(user_id: int):
    """
    Главное меню:
    - Всегда есть быстрые кнопки.
    - Если пользователь НЕ зарегистрирован: показываем доступные роли + waitlist.
    - Если зарегистрирован: показываем "Инфо" и "Отменить регистрацию", роли не показываем.
    """
    keyboard = []

    quick_row, player = _quick_buttons_row(user_id)

    # Если зарегистрирован — добавляем Инфо/Отмену на отдельную строку,
    # чтобы не плодить callback, которых нет в handlers.py
    if player and player.get("status") == "registered":
        keyboard.append(quick_row)
        keyboard.append([
            InlineKeyboardButton("👤 Инфо", callback_data="my_info"),
            InlineKeyboardButton("🗑️ Отменить регистрацию", callback_data="delete_registration"),
        ])
        return InlineKeyboardMarkup(keyboard)

    # Не зарегистрирован: быстрые кнопки + список ролей + waitlist
    keyboard.append(quick_row)

    free_roles = db.get_free_roles()
    if free_roles:
        for role, cap, taken in free_roles:
            # callback_data должен быть коротким (лимит 64 байта) — role у вас короткие, ок
            keyboard.append([
                InlineKeyboardButton(
                    f"🎭 {role} ({taken}/{cap})",
                    callback_data=f"role_{role}",
                )
            ])
    else:
        # ролей нет — всё равно даём возможность записаться в ожидание
        pass

    keyboard.append([InlineKeyboardButton("📋 Список ожидания", callback_data="waitlist")])
    return InlineKeyboardMarkup(keyboard)


def back_menu_keyboard():
    """Простой возврат в главное меню"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="menu")]])


def rules_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📖 О ролях", callback_data="roles_menu")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)
