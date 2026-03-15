# logger_setup.py
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Ограниченный набор форматов и обработчиков
def setup_logger(log_path: Path, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5):
    # Создаём директорию под лог, если её нет
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Формат записи
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Обработчик файла (с ротацией)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Обработчик консоли
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Убираем старые хендлеры, чтобы не дублировать
    root_logger.handlers.clear()

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    return root_logger
