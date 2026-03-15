# config.py
from pathlib import Path

# Путь к папке с ботом
BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "roles.json"
LOG_PATH = BASE_DIR / "bot.log"

# Токен бота (реально лучше не хранить в коде, но для простоты)
BOT_TOKEN = "8745137615:AAE1yzSxPWUts_8PIlbuTxcM0JcaHuaoMCI"

# Список ID админов
ADMIN_IDS = [5191400692]

# Определение ролей и количество слотов для каждой
ROLES = {
    "Кузнец-лучник": 2,
    "Мастер": 2,
    "Повар": 1,
    "Охотник": 1,
    "Работяга": 2,
}

# Общее количество слотов (вычисляется один раз)
TOTAL_SLOTS = sum(ROLES.values())
