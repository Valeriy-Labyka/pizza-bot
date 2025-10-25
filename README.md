# 🍕 Pizza_Store39 — Telegram-бот для заказа пиццы

Полнофункциональный бот для доставки пиццы с:
- 🛒 Корзиной и кастомизацией пиццы
- 🚚 Бесплатной доставкой от 800₽
- 💳 Оплатой по реквизитам (СБП: Сбер/Тинькофф)
- 🔐 Админкой для управления заказами
- 📱 Кнопкой отправки номера телефона

## 🚀 Развёртывание на Render

1. Создайте аккаунт на [Render](https://render.com/)
2. Подключите GitHub-репозиторий
3. Добавьте переменные окружения:
   - `BOT_TOKEN` — токен от @BotFather
   - `ADMIN_USER_ID` — ваш Telegram ID
   - `KITCHEN_CHAT_ID` — (опционально) ID чата кухни
   - `PAYMENT_CARD_NUMBER` — номер карты для оплаты
   - `PAYMENT_BANK_NAME` — название банка (например, "Тинькофф")
   - `RENDER_EXTERNAL_URL` — URL вашего сервиса вида `https://ваш-бот.onrender.com`
   - `DATABASE_URL` — URL PostgreSQL (Render создаёт его автоматически)
4. Выберите тип сервиса: **Web Service**
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `python main.py`
7. Нажмите **Deploy**

> ⚠️ Бот использует `MemoryStorage` — данные (корзина, FSM) **теряются при перезапуске**. Для продакшена рекомендуется Redis или сохранение состояний в БД.

## 📞 Поддержка
+7 (952) 114-87-67