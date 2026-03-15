# bot.py
import logging
from pathlib import Path

# Конфигурация и зависимости
from config import BOT_TOKEN
from logger_setup import setup_logger
from handlers import (
    start_handler,
    admin_handler,
    message_handler,
    callback_handler,
)


def main():
    # Настраиваем логирование
    log_path = Path(__file__).resolve().parent / "bot.log"
    setup_logger(log_path)

    # Создаём Application
    from telegram.ext import Application

    app = Application.builder().token(BOT_TOKEN).build()

    # Добавляем хендлеры
    app.add_handler(start_handler)
    app.add_handler(admin_handler)
    app.add_handler(message_handler)
    app.add_handler(callback_handler)

    logging.info("✅ Бот запущен. Используйте /start или /admin.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
