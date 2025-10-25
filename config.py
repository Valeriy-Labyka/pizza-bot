import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
KITCHEN_CHAT_ID = int(os.getenv("KITCHEN_CHAT_ID")) if os.getenv("KITCHEN_CHAT_ID") else None

PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER")
PAYMENT_BANK_NAME = os.getenv("PAYMENT_BANK_NAME")