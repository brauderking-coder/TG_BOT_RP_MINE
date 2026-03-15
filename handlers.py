# handlers.py
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import ADMIN_IDS, TOTAL_SLOTS
from storage import db, user_states
from texts import ROLE_INFO, RULES_TEXT
from keyboards import (
    roles_menu_keyboard,
    role_detail_keyboard,
    main_menu_keyboard,
    back_menu_keyboard,
    rules_menu_keyboard,
)

logger = logging.getLogger(__name__)


# --- Внутренние утилиты ---

def _ensure_user_state(user_id: int) -> dict:
    if user_id not in user_states or not isinstance(user_states.get(user_id), dict):
        user_states[user_id] = {}
    user_states[user_id].setdefault("state", "start")
    user_states[user_id].setdefault("last_msg_id", None)
    return user_states[user_id]


async def _safe_delete_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int | None,
) -> None:
    if not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug(f"delete_message failed chat_id={chat_id} msg_id={message_id}: {e}")


async def _safe_delete_update_message(update: Update) -> None:
    try:
        if update and update.effective_message:
            await update.effective_message.delete()
    except Exception as e:
        logger.debug(f"delete user message failed: {e}")


async def _send_new_and_cleanup(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool | None = None,
    delete_user_message: Update | None = None,
    extra_delete_message_ids: list[int] | None = None,
) -> int:
    """
    Всегда отправляем НОВОЕ сообщение.
    Потом удаляем:
    - предыдущее сообщение бота (last_msg_id)
    - сообщение пользователя (если передано delete_user_message)
    - любые extra message_id (например сообщение с inline-кнопками, по которому кликнули)
    """
    st = _ensure_user_state(user_id)
    prev_bot_msg_id = st.get("last_msg_id")

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
    new_bot_msg_id = msg.message_id

    # удаляем предыдущее сообщение бота
    if prev_bot_msg_id and prev_bot_msg_id != new_bot_msg_id:
        await _safe_delete_message(context, chat_id, prev_bot_msg_id)

    # удаляем сообщение, по которому кликнули (и прочие)
    if extra_delete_message_ids:
        for mid in extra_delete_message_ids:
            if mid and mid != new_bot_msg_id:
                await _safe_delete_message(context, chat_id, mid)

    # удаляем сообщение пользователя
    if delete_user_message:
        await _safe_delete_update_message(delete_user_message)

    st["last_msg_id"] = new_bot_msg_id
    return new_bot_msg_id


def _build_start_text() -> str:
    text = """<b>Добро пожаловать на РП‑сервер Minecraft!</b>

Выберите роль (из доступных оставшихся):"""

    free_roles = db.get_free_roles()
    if free_roles:
        text += "\n\n<b>Доступные роли:</b>"
        for role, cap, taken in free_roles:
            free = cap - taken
            text += f"\n• <b>{role}</b>: {taken}/{cap} (свободно: {free})"
    else:
        text += (
            "\n\n❌ Все роли заняты. Заходите в список ожидания — "
            "мы добавим вас при первой возможности."
        )
    return text


def _build_registered_start_text(player: dict) -> str:
    return (
        "✅ Вы уже зарегистрированы.\n\n"
        "Нажмите кнопку «Инфо», чтобы посмотреть ваши данные.\n\n"
        f"🎭 Ваша роль: <b>{player.get('role') or '—'}</b>"
    )


def _build_waitlist_start_text(player: dict) -> str:
    return (
        "⏳ Вы уже в <b>списке ожидания</b>.\n\n"
        "Мы добавим вас в игру при первой возможности.\n"
        "Вы можете открыть «Правила» или «О ролях»."
    )


def _infer_flow_state_from_player(player: dict | None) -> str:
    """
    Синхронизация in-memory state с тем, что лежит в JSON.
    """
    if not player:
        return "start"

    status = player.get("status")
    if status == "registered":
        return "registered"
    if status == "waitlist":
        return "waitlist"
    if status == "waiting_minecraft_name":
        return "waiting_minecraft_name"
    if status == "role_selected":
        # роль выбрана, ждём RP-имя
        return "waiting_rp_name"
    return "start"


# === Команды ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    st = _ensure_user_state(user_id)

    player = db.get_player(user_id)
    st["state"] = _infer_flow_state_from_player(player)

    # 1) Уже зарегистрирован — НЕ показываем выбор роли
    if player and player.get("status") == "registered":
        text = _build_registered_start_text(player)
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    # 2) В waitlist — тоже НЕ показываем выбор роли
    if player and player.get("status") == "waitlist":
        text = _build_waitlist_start_text(player)
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    # 3) Если роль уже выбрана, но регистрация не завершена — продолжаем с нужного шага
    if player and player.get("status") == "role_selected":
        role = player.get("role")
        text = (
            f"🎭 У вас уже выбрана роль <b>{role}</b>.\n\n"
            "✏️ Введите ваше RP имя (например: <b>Бьёрн</b>):"
        )
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=None,
        )
        st["state"] = "waiting_rp_name"
        return

    if player and player.get("status") == "waiting_minecraft_name":
        text = "✏️ Напишите ваш ник в Minecraft (например: <b>Bjorn</b>):"
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=None,
        )
        st["state"] = "waiting_minecraft_name"
        return

    # 4) Новый пользователь — стандартный сценарий выбора роли
    text = _build_start_text()
    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        reply_markup=main_menu_keyboard(user_id),
    )
    st["state"] = "start"


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.effective_message.reply_text("⛔ Доступ запрещён", parse_mode="HTML")
        return
    await show_admin_panel(update, context)


# === Ввод текста (RP имя / Minecraft ник) ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    incoming_text = (update.message.text or "").strip()
    st = _ensure_user_state(user_id)

    # Подстрахуемся: если state в памяти потерялся, восстановим из базы
    if st.get("state") in (None, "start"):
        st["state"] = _infer_flow_state_from_player(db.get_player(user_id))

    state = st.get("state", "start")

    if state == "waiting_rp_name":
        ok = db.set_rp_name(user_id, incoming_text)
        if not ok:
            # если вдруг статус в json не тот — восстановимся
            st["state"] = _infer_flow_state_from_player(db.get_player(user_id))

        text = (
            "✅ RP имя сохранено.\n\n"
            "✏️ Напишите ваш ник в Minecraft (например: <b>Bjorn</b>):"
        )
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=None,
            delete_user_message=update,
        )
        st["state"] = "waiting_minecraft_name"
        return

    if state == "waiting_minecraft_name":
        ok = db.set_minecraft_name(user_id, incoming_text)
        if not ok:
            st["state"] = _infer_flow_state_from_player(db.get_player(user_id))

        player = db.get_player(user_id)
        if player and player.get("status") == "registered":
            text = (
                "✅ Регистрация прошла успешно.\n\n"
                "Чтобы посмотреть ваши данные, нажмите кнопку «Инфо»."
            )
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_markup=main_menu_keyboard(user_id),
                delete_user_message=update,
            )
            st["state"] = "registered"
        else:
            text = "❌ Ошибка регистрации. Попробуйте «Начать сначала»."
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_markup=main_menu_keyboard(user_id),
                delete_user_message=update,
            )
            st["state"] = "start"
        return

    # Если пользователь пишет в любом другом состоянии — удаляем его сообщение и показываем корректный экран
    player = db.get_player(user_id)
    if player and player.get("status") == "registered":
        text = _build_registered_start_text(player)
    elif player and player.get("status") == "waitlist":
        text = _build_waitlist_start_text(player)
    else:
        text = "Выберите действие кнопками ниже."

    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        reply_markup=main_menu_keyboard(user_id),
        delete_user_message=update,
    )
    st["state"] = _infer_flow_state_from_player(player)


# === Inline-кнопки ===

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    username = query.from_user.username or query.from_user.first_name
    st = _ensure_user_state(user_id)

    await query.answer()
    data = query.data
    clicked_msg_id = query.message.message_id if query.message else None

    if data == "menu":
        # menu должен вести в "правильное" меню по статусу игрока
        player = db.get_player(user_id)
        st["state"] = _infer_flow_state_from_player(player)

        if player and player.get("status") == "registered":
            text = _build_registered_start_text(player)
        elif player and player.get("status") == "waitlist":
            text = _build_waitlist_start_text(player)
        else:
            text = _build_start_text()

        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=main_menu_keyboard(user_id),
            extra_delete_message_ids=[clicked_msg_id],
        )
        return

    if data == "my_info":
        await show_my_info(update, context)
        return

    if data == "back_my_info":
        await show_my_info(update, context)
        return

    if data == "roles_menu":
        await open_roles_main_menu(update, context)
        return

    if data == "rules_menu":
        await open_rules_menu(update, context)
        return

    if data.startswith("role_info_"):
        await show_role_detail(update, context)
        return

    if data.startswith("role_"):
        role = data.split("_", 1)[1]

        # Если пользователь уже зарегистрирован — не даём выбрать роль тут (только через "Начать сначала")
        player = db.get_player(user_id)
        if player and player.get("status") == "registered":
            text = "✅ Вы уже зарегистрированы. Чтобы сменить роль — нажмите «Начать сначала»."
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_markup=main_menu_keyboard(user_id),
                extra_delete_message_ids=[clicked_msg_id],
            )
            st["state"] = "registered"
            return

        ok, msg_text = db.assign_role(user_id, username, role)
        if ok:
            text = (
                f"🎭 Вы выбрали роль <b>{role}</b>.\n\n"
                "✏️ Введите ваше RP имя (например: <b>Бьёрн</b>):"
            )
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_markup=None,
                extra_delete_message_ids=[clicked_msg_id],
            )
            st["state"] = "waiting_rp_name"
        else:
            text = f"❌ {msg_text}"
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_markup=back_menu_keyboard(),
                extra_delete_message_ids=[clicked_msg_id],
            )
            st["state"] = "start"
        return

    if data == "waitlist":
        # если уже зарегистрирован — не переводим в waitlist
        player = db.get_player(user_id)
        if player and player.get("status") == "registered":
            text = "✅ Вы уже зарегистрированы. Список ожидания вам не нужен."
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_markup=main_menu_keyboard(user_id),
                extra_delete_message_ids=[clicked_msg_id],
            )
            st["state"] = "registered"
            return

        db.add_to_waitlist(user_id, username)
        text = (
            f"✅ <b>{username}</b> добавлен в список ожидания.\n"
            "Мы добавим вас в игру при первой возможности."
        )
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=main_menu_keyboard(user_id),
            extra_delete_message_ids=[clicked_msg_id],
        )
        st["state"] = "waitlist"
        return

    if data == "reset_registration":
        db.reset_player_registration(user_id)
        text = "🔄 Вы начали регистрацию сначала.\n\nВыберите роль:"
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=main_menu_keyboard(user_id),
            extra_delete_message_ids=[clicked_msg_id],
        )
        st["state"] = "start"
        return

    if data == "delete_registration":
        was_removed = db.remove_player(user_id)
        if was_removed:
            text = "🗑️ Регистрация отменена. Вы можете зарегистрироваться снова."
        else:
            text = "❌ Запись не найдена."
        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=main_menu_keyboard(user_id),
            extra_delete_message_ids=[clicked_msg_id],
        )
        st["state"] = "start"
        return

    if data == "admin_panel":
        if user_id not in ADMIN_IDS:
            await query.answer("⛔ Доступ запрещён", show_alert=True)
            return
        await show_admin_panel(update, context)
        return

    if data.startswith("remove_"):
        if user_id not in ADMIN_IDS:
            await query.answer("⛔ Доступ запрещён", show_alert=True)
            return

        try:
            telegram_id = int(data.split("_", 1)[1])
        except ValueError:
            await _send_new_and_cleanup(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                text="❌ Ошибка данных.",
                reply_markup=back_menu_keyboard(),
                extra_delete_message_ids=[clicked_msg_id],
            )
            st["state"] = "start"
            return

        if db.remove_player(telegram_id):
            text = "✅ Игрок удалён и роль освобождена."
        else:
            text = "❌ Игрок не найден."

        await _send_new_and_cleanup(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            reply_markup=back_menu_keyboard(),
            extra_delete_message_ids=[clicked_msg_id],
        )
        st["state"] = "start"
        return

    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text="❌ Неизвестная команда. Откройте главное меню.",
        reply_markup=main_menu_keyboard(user_id),
        extra_delete_message_ids=[clicked_msg_id],
    )
    st["state"] = "start"


# === Вспомогательные функции (меню / страницы) ===

async def show_my_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    player = db.get_player(user_id)
    st = _ensure_user_state(user_id)

    clicked_msg_id = query.message.message_id if query and query.message else None

    if not player or player.get("status") != "registered":
        text = "❌ Вы не зарегистрированы."
        keyboard = back_menu_keyboard()
    else:
        text = f"""<b>👤 Ваши данные:</b>

👤 Telegram: <b>{player['username']}</b>
🎭 Роль: <b>{player['role']}</b>
🏛️ RP имя: <b>{player['rp_name'] or 'Не указано'}</b>
🎮 Minecraft ник: <b>{player.get('minecraft_username') or 'Не указано'}</b>"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Начать сначала", callback_data="reset_registration"),
                InlineKeyboardButton("🗑️ Отменить регистрацию", callback_data="delete_registration"),
            ],
            [
                InlineKeyboardButton("📖 О ролях", callback_data="roles_menu"),
                InlineKeyboardButton("📜 Правила игры", callback_data="rules_menu"),
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="menu")],
        ])

    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        reply_markup=keyboard,
        extra_delete_message_ids=[clicked_msg_id],
    )
    st["state"] = _infer_flow_state_from_player(player)


async def show_role_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    st = _ensure_user_state(user_id)

    clicked_msg_id = query.message.message_id if query.message else None

    role_key = query.data.split("_", 2)[-1]
    info = ROLE_INFO.get(role_key, "❌ Неизвестная роль.")
    text = (
        f"<b>🎭 {role_key}</b>\n\n"
        f"{info}\n\n"
        "Хотите выбрать эту роль?\n"
        "Нажмите «🏠 Главное меню» и выберите её в списке ролей."
    )

    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        reply_markup=role_detail_keyboard(role_key),
        extra_delete_message_ids=[clicked_msg_id],
    )
    st["state"] = st.get("state", "start")


async def open_roles_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    st = _ensure_user_state(user_id)

    clicked_msg_id = query.message.message_id if query.message else None

    text = "<b>📖 О ролях</b>\n\nВыберите роль, чтобы узнать подробности:"
    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        reply_markup=roles_menu_keyboard(),
        extra_delete_message_ids=[clicked_msg_id],
    )
    st["state"] = st.get("state", "start")


async def open_rules_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    st = _ensure_user_state(user_id)

    clicked_msg_id = query.message.message_id if query.message else None

    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=RULES_TEXT,
        reply_markup=rules_menu_keyboard(),
        disable_web_page_preview=True,
        extra_delete_message_ids=[clicked_msg_id],
    )
    st["state"] = st.get("state", "start")


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    st = _ensure_user_state(user_id)

    if user_id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
        else:
            await update.effective_message.reply_text("⛔ Доступ запрещён", parse_mode="HTML")
        return

    players_by_role = db.get_players_by_role()
    free_slots = db.get_free_slots_count()
    players = db.data["players"]

    registered = [p for p in players if p.get("status") == "registered"]
    waitlist = [p for p in players if p.get("status") == "waitlist"]

    text = f"""<b>👑 Админ‑панель</b>

📊 <b>Статистика</b>:
• Зарегистрировано: <b>{len(registered)}/{TOTAL_SLOTS}</b>
• Свободно: <b>{free_slots}</b>
• В ожидании: <b>{len(waitlist)}</b>

<b>🎭 Зарегистрированные игроки</b>:"""

    keyboard = []

    if players_by_role:
        for role, role_players in players_by_role.items():
            cap = db.data["roles"][role]["capacity"]
            took = len(role_players)
            text += f"\n\n<b>🎮 {role}</b> ({took}/{cap}):"
            for p in role_players:
                text += (
                    f"\n  • Роль: <b>{p['role']}</b> "
                    f"• RP: <b>{p['rp_name'] or '—'}</b> "
                    f"• Minecraft: <b>{p.get('minecraft_username') or '—'}</b> "
                    f"• Имя TG: <b>{p['username']}</b> "
                    f"• ID: <code>{p['telegram_id']}</code>"
                )
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑 {p['username']} (ID: {p['telegram_id']})",
                        callback_data=f"remove_{p['telegram_id']}",
                    )
                ])
    else:
        text += "\n\n<i>Нет зарегистрированных игроков.</i>"

    if waitlist:
        text += "\n\n<b>📋 Список ожидания (waitlist)</b>:"
        for p in waitlist:
            text += (
                f"\n  • <b>{p['username']}</b> "
                f"• ID: <code>{p['telegram_id']}</code> "
                f"• Minecraft: <b>{p.get('minecraft_username') or '—'}</b> "
                f"• Роль: {p['role'] or '—'}"
            )
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 Waitlist {p['username']} (ID: {p['telegram_id']})",
                    callback_data=f"remove_{p['telegram_id']}",
                )
            ])

    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    clicked_msg_id = (
        update.callback_query.message.message_id
        if update.callback_query and update.callback_query.message
        else None
    )

    await _send_new_and_cleanup(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        reply_markup=reply_markup,
        extra_delete_message_ids=[clicked_msg_id],
    )
    st["state"] = st.get("state", "start")


# === Экспорт хендлеров ===

start_handler = CommandHandler("start", start)
admin_handler = CommandHandler("admin", admin_command)
message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
callback_handler = CallbackQueryHandler(button_callback)
