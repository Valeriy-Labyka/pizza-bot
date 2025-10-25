import os

# Обязательные переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не установлена!")

admin_user_id_raw = os.getenv("ADMIN_USER_ID")
if not admin_user_id_raw:
    raise ValueError("❌ Переменная ADMIN_USER_ID не установлена!")

try:
    ADMIN_USER_ID = int(admin_user_id_raw)
except (ValueError, TypeError):
    raise ValueError("❌ Переменная ADMIN_USER_ID должна быть целым числом!")

# Опциональные переменные
KITCHEN_CHAT_ID = os.getenv("KITCHEN_CHAT_ID")
if KITCHEN_CHAT_ID:
    try:
        KITCHEN_CHAT_ID = int(KITCHEN_CHAT_ID)
    except ValueError:
        raise ValueError("❌ KITCHEN_CHAT_ID должен быть целым числом!")

PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER")
PAYMENT_BANK_NAME = os.getenv("PAYMENT_BANK_NAME")

# Проверка платежных данных (если используется онлайн-оплата)
if not PAYMENT_CARD_NUMBER or not PAYMENT_BANK_NAME:
    print("⚠️ Внимание: PAYMENT_CARD_NUMBER или PAYMENT_BANK_NAME не заданы. Онлайн-оплата может не работать.")