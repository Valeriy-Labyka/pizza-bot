import os
import asyncio
import logging
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import BOT_TOKEN, ADMIN_USER_ID, KITCHEN_CHAT_ID, PAYMENT_CARD_NUMBER, PAYMENT_BANK_NAME
from database import init_db, save_order, get_user_orders, get_all_orders, update_order_status, delete_old_completed_orders
from keyboards import (
    main_menu, product_buttons, cart_keyboard, payment_keyboard, admin_keyboard, order_status_buttons,
    phone_keyboard, build_pizza_custom_keyboard, INGREDIENTS, cart_item_buttons
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_carts = {}
user_active_messages = {}
user_custom_pizzas = {}

async def cleanup_old_orders():
    while True:
        await asyncio.sleep(3600)
        await delete_old_completed_orders()

try:
    with open("menu_data.json", "r", encoding="utf-8") as f:
        MENU_DATA = json.load(f)
    logger.info("Файл menu_data.json успешно загружен.")
except Exception as e:
    logger.error(f"Ошибка при загрузке menu_data.json: {e}")
    MENU_DATA = {}


class OrderFlow(StatesGroup):
    waiting_for_address = State()
    waiting_for_phone = State()
    waiting_for_payment = State()
    waiting_for_receipt = State()
    custom_pizza = State()


class AdminFlow(StatesGroup):
    waiting_for_order_id = State()


def get_item_key(category: str, item_index: int, size: str = None, custom: bool = False, ingredients: dict = None):
    if custom:
        ing_str = "_".join([f"{k}{v}" for k, v in sorted(ingredients.items())]) if ingredients else ""
        return f"custom_{size}_{ing_str}"
    else:
        size_suffix = f"_{size}" if size else ""
        return f"{category}_{item_index}{size_suffix}"


def add_to_cart_safe(user_id: int, item_key: str, name: str, price_per_unit: int, quantity: int = 1, details: dict = None):
    if user_id not in user_carts:
        user_carts[user_id] = {}
    if item_key in user_carts[user_id]:
        user_carts[user_id][item_key]["quantity"] += quantity
    else:
        user_carts[user_id][item_key] = {
            "name": name,
            "price_per_unit": price_per_unit,
            "quantity": quantity,
            "details": details
        }


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_active_messages.pop(message.from_user.id, None)
    is_admin = (message.from_user.id == ADMIN_USER_ID)
    await message.answer(
        "🍕 <b>Добро пожаловать в Pizza_Store39!</b>\n"
        "Горячая пицца в Калининграде — быстро, вкусно, удобно!",
        reply_markup=main_menu(is_admin=is_admin),
        parse_mode="HTML"
    )


async def clear_active_messages(user_id: int, bot_instance: Bot):
    data = user_active_messages.get(user_id)
    if data:
        for msg_id in data.get("message_ids", []):
            try:
                await bot_instance.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass
        user_active_messages.pop(user_id, None)


@dp.message(F.text.in_({"🍕 Меню пицц", "🥗 Салаты и закуски", "🥤 Напитки"}))
async def show_category(message: types.Message, state: FSMContext):
    await state.clear()
    await clear_active_messages(message.from_user.id, bot)

    category_map = {
        "🍕 Меню пицц": "Пиццы",
        "🥗 Салаты и закуски": "Салаты и закуски",
        "🥤 Напитки": "Напитки"
    }
    category = category_map.get(message.text)
    if not category:
        await message.answer("❌ Неизвестная категория.", parse_mode="HTML")
        return

    items = MENU_DATA.get(category, [])
    if not items:
        await message.answer("📂 Категория пуста.", parse_mode="HTML")
        return

    category_short = {"Пиццы": "p", "Салаты и закуски": "s", "Напитки": "d"}[category]
    sent_ids = []
    for idx, item in enumerate(items):
        product_id = f"{category_short}{idx}"
        has_sizes = category == "Пиццы"

        if has_sizes:
            caption = f"<b>{item['name']}</b>\n{item['description']}\n\nМаленькая: <b>{item['price_small']}₽</b> | Большая: <b>{item['price_large']}₽</b>"
        else:
            caption = f"<b>{item['name']}</b>\n{item['description']}\n\nЦена: <b>{item['price_small']}₽</b>"

        kb = product_buttons(
            product_id=product_id,
            price_small=item.get("price_small"),
            price_large=item.get("price_large")
        )

        image_path = item.get("image_url", "").strip()
        try:
            sent = await message.answer_photo(
                photo=types.FSInputFile(image_path),
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except FileNotFoundError:
            logger.warning(f"Файл не найден: {image_path}")
            sent = await message.answer(caption, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить фото для {item['name']}: {e}")
            sent = await message.answer(caption, reply_markup=kb, parse_mode="HTML")
        sent_ids.append(sent.message_id)

    user_active_messages[message.from_user.id] = {
        "category": category,
        "message_ids": sent_ids
    }


@dp.message(F.text.in_({"🛒 Корзина", "ℹ️ О нас / Доставка", "🔐 Админка"}))
async def handle_main_menu_buttons(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state != OrderFlow.waiting_for_receipt.state:
        await state.clear()
        is_admin = (message.from_user.id == ADMIN_USER_ID)
        await message.answer("❌ Процесс оформления заказа отменён. Вы в главном меню.", reply_markup=main_menu(is_admin=is_admin), parse_mode="HTML")

    if message.text == "🛒 Корзина":
        await show_cart(message)
    elif message.text == "ℹ️ О нас / Доставка":
        await about(message)
    elif message.text == "🔐 Админка":
        await admin_cmd(message)


@dp.message(F.text == "📍 Мои заказы")
async def my_orders(message: types.Message, state: FSMContext):
    await state.clear()
    all_orders = await get_user_orders(message.from_user.id)
    if not all_orders:
        await message.answer("📭 У вас пока нет заказов.", parse_mode="HTML")
        return

    active_orders = [order for order in all_orders if order["status"] not in ('done', 'cancelled')]
    if not active_orders:
        await message.answer("📭 У вас нет активных заказов.", parse_mode="HTML")
        return

    status_map = {
        "new": "🆕 Новый",
        "cooking": "🍳 Готовится",
        "delivery": "🚚 Доставляется",
        "done": "✅ Завершён",
        "cancelled": "❌ Отменён"
    }
    text = "📦 <b>Ваши активные заказы:</b>\n\n"
    for i, order in enumerate(active_orders, 1):
        status = status_map.get(order["status"], order["status"])
        created_at_str = order["created_at"].strftime('%d.%m.%Y %H:%M')
        text += (
            f"<b>{i}.</b> Сумма: <b>{order['total']}₽</b>\n"
            f"Адрес: {order['address']}\n"
            f"Оплата: {order['payment_method']}\n"
            f"Статус: {status}\n"
            f"Время: {created_at_str}\n\n"
        )
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data.startswith("back_to_"))
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await clear_active_messages(callback.from_user.id, bot)
    is_admin = (callback.from_user.id == ADMIN_USER_ID)
    await callback.message.answer("📂 Выберите раздел:", reply_markup=main_menu(is_admin=is_admin), parse_mode="HTML")
    try:
        await callback.message.delete()
    except:
        pass


@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state != OrderFlow.custom_pizza.state:
        await state.clear()
        await callback.answer("❌ Процесс оформления заказа был отменён.", show_alert=True)
        await clear_active_messages(callback.from_user.id, bot)
        is_admin = (callback.from_user.id == ADMIN_USER_ID)
        await callback.message.answer("📂 Выберите раздел:", reply_markup=main_menu(is_admin=is_admin), parse_mode="HTML")
        return

    data = callback.data.replace("add_", "")
    size = None
    size_name = ""

    if data.endswith("_small"):
        product_key = data[:-6]
        size = "small"
        size_name = "Маленькая"
    elif data.endswith("_large"):
        product_key = data[:-6]
        size = "large"
        size_name = "Большая"
    else:
        product_key = data.replace("_nosize", "")
        size = "nosize"
        size_name = ""

    category_map_short = {"p": "Пиццы", "s": "Салаты и закуски", "d": "Напитки"}
    if not product_key or len(product_key) < 2:
        await callback.answer("❌ Некорректный ID товара.", show_alert=True)
        return

    category_short = product_key[0]
    item_index_str = product_key[1:]
    try:
        item_index = int(item_index_str)
    except ValueError:
        await callback.answer("❌ Ошибка индекса товара.", show_alert=True)
        return

    target_category = category_map_short.get(category_short)
    if not target_category:
        await callback.answer("❌ Неизвестная категория.", show_alert=True)
        return

    items = MENU_DATA.get(target_category, [])
    if item_index >= len(items):
        await callback.answer("❌ Товар не найден (индекс вне диапазона).", show_alert=True)
        return

    found_item = items[item_index]

    if found_item["name"] == "🍕 Собери сам":
        base_price = found_item["price_small"] if size == "small" else found_item["price_large"]
        user_custom_pizzas[callback.from_user.id] = {
            "size": size,
            "base_price": base_price,
            "ingredients": {}
        }
        await callback.message.edit_caption(
            caption=f"🍕 <b>Соберите свою пиццу ({size_name})</b>\n"
                    f"Основа: {base_price}₽\n\nВыберите ингредиенты:",
            reply_markup=build_pizza_custom_keyboard({}, base_price, size),
            parse_mode="HTML"
        )
        await state.set_state(OrderFlow.custom_pizza)
        return

    if target_category == "Пиццы":
        if size == "small":
            price = found_item.get("price_small")
        elif size == "large":
            price = found_item.get("price_large")
        else:
            price = found_item.get("price_small")
            size_name = "Маленькая"
        if price is None:
            await callback.answer("❌ Цена не указана для этого размера.", show_alert=True)
            return
        name = f"{found_item['name']} ({size_name})"
    else:
        price = found_item.get("price_small")
        if price is None:
            await callback.answer("❌ Цена не указана.", show_alert=True)
            return
        name = found_item["name"]

    item_key = get_item_key(target_category, item_index, size)
    add_to_cart_safe(callback.from_user.id, item_key, name, price, 1)
    await callback.answer(f"✅ {name} добавлена в корзину!")


@dp.callback_query(OrderFlow.custom_pizza, F.data.startswith("custom_add_"))
async def custom_add_ingredient(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_custom_pizzas:
        await callback.answer("❌ Сессия устарела. Начните заново.", show_alert=True)
        return

    ingredient_key = callback.data.replace("custom_add_", "")
    if ingredient_key not in INGREDIENTS:
        await callback.answer("❌ Неизвестный ингредиент.", show_alert=True)
        return

    pizza_data = user_custom_pizzas[user_id]
    current = pizza_data["ingredients"].get(ingredient_key, 0)
    pizza_data["ingredients"][ingredient_key] = current + 50

    await callback.message.edit_caption(
        caption=f"🍕 <b>Соберите свою пиццу ({'Маленькая' if pizza_data['size'] == 'small' else 'Большая'})</b>\n"
                f"Основа: {pizza_data['base_price']}₽\n\nВыберите ингредиенты:",
        reply_markup=build_pizza_custom_keyboard(pizza_data["ingredients"], pizza_data["base_price"], pizza_data["size"]),
        parse_mode="HTML"
    )


@dp.callback_query(OrderFlow.custom_pizza, F.data == "custom_cancel")
async def custom_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_custom_pizzas.pop(callback.from_user.id, None)
    await back_to_main(callback, state)


@dp.callback_query(OrderFlow.custom_pizza, F.data == "custom_done")
async def custom_done(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_custom_pizzas:
        await callback.answer("❌ Сессия устарела.", show_alert=True)
        return

    pizza_data = user_custom_pizzas[user_id]
    total_extra = sum((grams // 50) * INGREDIENTS[k][1] for k, grams in pizza_data["ingredients"].items())
    total_price = pizza_data["base_price"] + total_extra

    size_name = "Маленькая" if pizza_data["size"] == "small" else "Большая"
    ingredients_list = []
    for k, grams in pizza_data["ingredients"].items():
        if grams > 0:
            name = INGREDIENTS[k][0]
            ingredients_list.append(f"{name} {grams}г")
    ingredients_str = ", ".join(ingredients_list) if ingredients_list else "без добавок"
    name = f"Пицца Собери сам ({size_name})"

    item_key = get_item_key("Пиццы", -1, pizza_data["size"], custom=True, ingredients=pizza_data["ingredients"])
    add_to_cart_safe(
        user_id,
        item_key,
        name,
        total_price,
        1,
        details={
            "size": size_name,
            "base_price": pizza_data["base_price"],
            "ingredients": dict(pizza_data["ingredients"])
        }
    )

    await callback.answer("✅ Пицца добавлена в корзину!", show_alert=True)
    await state.clear()
    user_custom_pizzas.pop(user_id, None)

    # === ИСПРАВЛЕНИЕ: не редактируем фото, а отправляем новое сообщение с корзиной ===
    cart = user_carts.get(user_id, {})
    if not cart:
        await callback.message.answer("📭 Корзина пуста.", parse_mode="HTML")
        try:
            await callback.message.delete()
        except:
            pass
        return

    subtotal = sum(item["price_per_unit"] * item["quantity"] for item in cart.values())
    delivery_cost = 0 if subtotal >= 800 else 150
    total_with_delivery = subtotal + delivery_cost

    text = "🛒 <b>Ваш заказ:</b>\n\n"
    for item_key, item in cart.items():
        name = item["name"]
        if "Собери сам" in name and "details" in item:
            details = item["details"]
            ingredients_str = ", ".join([f"{INGREDIENTS[k][0]} {v}г" for k, v in details["ingredients"].items()])
            name = f"{name} + {ingredients_str}"
        text += f"• {name} — <b>{item['price_per_unit']}₽</b> × {item['quantity']} = <b>{item['price_per_unit'] * item['quantity']}₽</b>\n"
    text += f"\n📦 Сумма товаров: <b>{subtotal}₽</b>\n"
    text += f"🚚 Доставка: {'Бесплатно' if delivery_cost == 0 else f'{delivery_cost}₽'}\n"
    text += f"\n<b>Итого к оплате: {total_with_delivery}₽</b>"

    # Удаляем старое фото-сообщение
    try:
        await callback.message.delete()
    except:
        pass

    # Отправляем новое текстовое сообщение с корзиной
    await callback.message.answer(text, reply_markup=cart_keyboard(), parse_mode="HTML")


async def show_cart_by_callback(callback: types.CallbackQuery):
    cart = user_carts.get(callback.from_user.id, {})
    if not cart:
        try:
            if callback.message.text is not None:
                await callback.message.edit_text("📭 Корзина пуста.", parse_mode="HTML")
            else:
                await callback.message.answer("📭 Корзина пуста.", parse_mode="HTML")
                await callback.message.delete()
        except TelegramBadRequest as e:
            if "there is no text in the message to edit" in str(e):
                await callback.message.answer("📭 Корзина пуста.", parse_mode="HTML")
                try:
                    await callback.message.delete()
                except:
                    pass
            else:
                raise
        return

    subtotal = sum(item["price_per_unit"] * item["quantity"] for item in cart.values())
    delivery_cost = 0 if subtotal >= 800 else 150
    total_with_delivery = subtotal + delivery_cost

    text = "🛒 <b>Ваш заказ:</b>\n\n"
    for item_key, item in cart.items():
        name = item["name"]
        if "Собери сам" in name and "details" in item:
            details = item["details"]
            ingredients_str = ", ".join([f"{INGREDIENTS[k][0]} {v}г" for k, v in details["ingredients"].items()])
            name = f"{name} + {ingredients_str}"
        text += f"• {name} — <b>{item['price_per_unit']}₽</b> × {item['quantity']} = <b>{item['price_per_unit'] * item['quantity']}₽</b>\n"
    text += f"\n📦 Сумма товаров: <b>{subtotal}₽</b>\n"
    text += f"🚚 Доставка: {'Бесплатно' if delivery_cost == 0 else f'{delivery_cost}₽'}\n"
    text += f"\n<b>Итого к оплате: {total_with_delivery}₽</b>"

    try:
        if callback.message.text is not None:
            await callback.message.edit_text(text, reply_markup=cart_keyboard(), parse_mode="HTML")
        else:
            # Это медиа-сообщение или без текста — отправляем новое
            await callback.message.answer(text, reply_markup=cart_keyboard(), parse_mode="HTML")
            await callback.message.delete()
    except TelegramBadRequest as e:
        if "there is no text in the message to edit" in str(e):
            await callback.message.answer(text, reply_markup=cart_keyboard(), parse_mode="HTML")
            try:
                await callback.message.delete()
            except:
                pass
        else:
            raise

    await callback.answer()


@dp.message(F.text == "🛒 Корзина")
async def show_cart(message: types.Message):
    cart = user_carts.get(message.from_user.id, {})
    if not cart:
        await message.answer("📭 Корзина пуста.", parse_mode="HTML")
        return

    subtotal = sum(item["price_per_unit"] * item["quantity"] for item in cart.values())
    delivery_cost = 0 if subtotal >= 800 else 150
    total_with_delivery = subtotal + delivery_cost

    text = "🛒 <b>Ваш заказ:</b>\n\n"
    for item_key, item in cart.items():
        name = item["name"]
        if "Собери сам" in name and "details" in item:
            details = item["details"]
            ingredients_str = ", ".join([f"{INGREDIENTS[k][0]} {v}г" for k, v in details["ingredients"].items()])
            name = f"{name} + {ingredients_str}"
        text += f"• {name} — <b>{item['price_per_unit']}₽</b> × {item['quantity']} = <b>{item['price_per_unit'] * item['quantity']}₽</b>\n"
    text += f"\n📦 Сумма товаров: <b>{subtotal}₽</b>\n"
    text += f"🚚 Доставка: {'Бесплатно' if delivery_cost == 0 else f'{delivery_cost}₽'}\n"
    text += f"\n<b>Итого к оплате: {total_with_delivery}₽</b>"

    await message.answer(text, reply_markup=cart_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_carts.pop(callback.from_user.id, None)
    try:
        await callback.message.edit_text("🗑 Корзина очищена.", parse_mode="HTML")
    except TelegramBadRequest:
        pass
    is_admin = (callback.from_user.id == ADMIN_USER_ID)
    await callback.message.answer("📂 Выберите раздел:", reply_markup=main_menu(is_admin=is_admin), parse_mode="HTML")


@dp.callback_query(F.data.startswith("cart_"))
async def cart_manage(callback: types.CallbackQuery):
    parts = callback.data.split("_", 2)
    if len(parts) < 3:
        await callback.answer("❌ Некорректная команда.", show_alert=True)
        return
    action, item_key = parts[1], parts[2]
    cart = user_carts.get(callback.from_user.id, {})
    if item_key not in cart:
        await callback.answer("❌ Товар не найден в корзине.", show_alert=True)
        return

    if action == "inc":
        cart[item_key]["quantity"] += 1
    elif action == "dec":
        if cart[item_key]["quantity"] > 1:
            cart[item_key]["quantity"] -= 1
        else:
            del cart[item_key]
    elif action == "del":
        del cart[item_key]

    if not cart:
        try:
            await callback.message.edit_text("📭 Корзина пуста.", parse_mode="HTML")
        except TelegramBadRequest:
            await callback.message.answer("📭 Корзина пуста.", parse_mode="HTML")
        return

    item = cart.get(item_key)
    if item:
        await callback.message.edit_reply_markup(reply_markup=cart_item_buttons(item_key, item["quantity"]))
    else:
        await show_cart_by_callback(callback)


@dp.callback_query(F.data == "checkout")
async def checkout_start(callback: types.CallbackQuery, state: FSMContext):
    cart = user_carts.get(callback.from_user.id, {})
    if not cart:
        await callback.answer("📭 Корзина пуста!", show_alert=True)
        return

    await callback.message.answer(
        "📍 Укажите адрес доставки и, при необходимости, дополнительные инструкции для курьера (подъезд, код, этаж и т.д.):",
        parse_mode="HTML"
    )
    await state.set_state(OrderFlow.waiting_for_address)


@dp.message(OrderFlow.waiting_for_address)
async def handle_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer(
        "📞 Укажите ваш номер телефона для связи:\n"
        "• Нажмите кнопку <b>«Отправить номер»</b> ниже\n"
        "• Или введите вручную",
        reply_markup=phone_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(OrderFlow.waiting_for_phone)


@dp.message(OrderFlow.waiting_for_phone, F.contact)
async def phone_contact(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await message.answer("💳 Выберите способ оплаты:", reply_markup=payment_keyboard(), parse_mode="HTML")
    await state.set_state(OrderFlow.waiting_for_payment)


@dp.message(OrderFlow.waiting_for_phone, F.text)
async def phone_text(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.replace("+", "").replace(" ", "").replace("-", "").isdigit() or len(phone) < 10:
        await message.answer("❌ Неверный формат номера. Пожалуйста, введите номер телефона заново.", parse_mode="HTML")
        return
    await state.update_data(phone=phone)
    await message.answer("💳 Выберите способ оплаты:", reply_markup=payment_keyboard(), parse_mode="HTML")
    await state.set_state(OrderFlow.waiting_for_payment)


@dp.callback_query(OrderFlow.waiting_for_payment, F.data.startswith("pay_"))
async def payment_selected(callback: types.CallbackQuery, state: FSMContext):
    payment_method_map = {"pay_online": "💳 Онлайн", "pay_cash": "💵 Наличными"}
    payment = payment_method_map.get(callback.data, "Неизвестно")
    await state.update_data(payment_method=payment)

    data = await state.get_data()
    cart = user_carts.get(callback.from_user.id, {})
    if not cart:
        await callback.message.answer("❌ Корзина пуста. Повторите заказ.", parse_mode="HTML")
        await state.clear()
        return

    if "address" not in data or "phone" not in data:
        await callback.message.answer("❌ Не хватает данных. Начните снова.", parse_mode="HTML")
        await state.clear()
        return

    subtotal = sum(item["price_per_unit"] * item["quantity"] for item in cart.values())
    delivery_cost = 0 if subtotal >= 800 else 150
    total_with_delivery = subtotal + delivery_cost

    items_list = []
    is_custom_order = False
    for item in cart.values():
        item_dict = {
            "name": item["name"],
            "price": item["price_per_unit"],
            "quantity": item["quantity"]
        }
        if "Собери сам" in item["name"] and "details" in item:
            is_custom_order = True
            details = item["details"]
            ingredients_str = ", ".join([f"{INGREDIENTS[k][0]} {v}г" for k, v in details["ingredients"].items()])
            item_dict["name"] = f"{item['name']} ({details['size']}) + {ingredients_str}"
        items_list.append(item_dict)

    order_id = await save_order(
        user_id=callback.from_user.id,
        items=items_list,
        total=total_with_delivery,
        address=data["address"],
        payment_method=payment,
        phone=data["phone"]
    )

    if order_id is None:
        logger.error("❌ Не удалось сохранить заказ")
        await callback.message.answer("❌ Ошибка при сохранении заказа.", parse_mode="HTML")
        await state.clear()
        return

    if payment == "💳 Онлайн":
        await callback.message.answer(
            f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
            f"📦 Сумма товаров: <b>{subtotal}₽</b>\n"
            f"🚚 Доставка: {'Бесплатно' if delivery_cost == 0 else f'{delivery_cost}₽'}\n"
            f"<b>Итого к оплате: {total_with_delivery}₽</b>\n\n"
            f"💳 Переведите <b>{total_with_delivery}₽</b> на карту:\n"
            f"<b>{PAYMENT_BANK_NAME}</b>\n"
            f"<code>{PAYMENT_CARD_NUMBER}</code>\n\n"
            f"📄 В назначении укажите: <b>Заказ #{order_id}</b>\n\n"
            f"❗ <b>Если вы уже оплатили, но не можете отправить чек — просто напишите в этот чат:</b>\n"
            f"• ФИО или номер телефона, с которого прошла оплата\n"
            f"• Последние 4 цифры карты\n"
            f"• Любые подтверждающие данные\n\n"
            f"Администратор вручную подтвердит вашу оплату.",
            parse_mode="HTML"
        )
        await state.set_state(OrderFlow.waiting_for_receipt)
        await state.update_data(order_id=order_id)

    else:
        await callback.message.answer(
            f"✅ <b>Заказ принят!</b>\n\n"
            f"📍 Адрес: {data['address']}\n"
            f"📞 Телефон: {data['phone']}\n"
            f"💳 Оплата: {payment}\n"
            f"📦 Сумма товаров: <b>{subtotal}₽</b>\n"
            f"🚚 Доставка: {'Бесплатно' if delivery_cost == 0 else f'{delivery_cost}₽'}\n"
            f"<b>Итого: {total_with_delivery}₽</b>\n\n"
            "🕒 Пицца уже в печи! 🍕",
            parse_mode="HTML"
        )

    if KITCHEN_CHAT_ID:
        try:
            order_text = ""
            if is_custom_order:
                order_text += "❗❗❗ <b>СПЕЦ ЗАКАЗ — ПИЦЦА СОБЕРИ САМ</b> ❗❗❗\n\n"
            order_text += f"🆕 <b>Новый заказ #{order_id}</b>\n"
            order_text += f"👤 Клиент: {callback.from_user.full_name}\n"
            order_text += f"🆔 ID: {callback.from_user.id}\n"
            order_text += f"📍 Адрес: {data['address']}\n"
            order_text += f"📞 Телефон: {data['phone']}\n"
            order_text += f"💳 Оплата: {payment}\n"
            order_text += f"📦 Сумма товаров: {subtotal}₽\n"
            order_text += f"🚚 Доставка: {'Бесплатно' if delivery_cost == 0 else f'{delivery_cost}₽'}\n"
            order_text += f"<b>Итого: {total_with_delivery}₽</b>\n\n"
            for item in items_list:
                order_text += f"• {item['name']} ×{item['quantity']} — {item['price'] * item['quantity']}₽\n"
            await bot.send_message(KITCHEN_CHAT_ID, order_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления на кухню: {e}")

    if payment != "💳 Онлайн":
        user_carts.pop(callback.from_user.id, None)
        await state.clear()
        is_admin = (callback.from_user.id == ADMIN_USER_ID)
        await callback.message.answer("🙏 Спасибо за заказ! 🍕", reply_markup=main_menu(is_admin=is_admin), parse_mode="HTML")


@dp.message(OrderFlow.waiting_for_receipt)
async def receive_payment_info(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id", "неизвестен")

    caption = (
        f"🧾 <b>Подтверждение оплаты по заказу #{order_id}</b>\n"
        f"👤 Пользователь: {message.from_user.full_name}\n"
        f"🆔 ID: {message.from_user.id}\n"
        f"🕒 Время: {message.date.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"<b>Сообщение от клиента:</b>\n{message.text or '—'}"
    )

    try:
        if message.photo:
            photo = message.photo[-1]
            await bot.send_photo(
                chat_id=ADMIN_USER_ID,
                photo=photo.file_id,
                caption=caption,
                parse_mode="HTML"
            )
        elif message.document:
            await bot.send_document(
                chat_id=ADMIN_USER_ID,
                document=message.document.file_id,
                caption=caption,
                parse_mode="HTML"
            )
        else:
            await bot.send_message(ADMIN_USER_ID, caption, parse_mode="HTML")

        await message.answer("✅ Информация получена! Администратор проверит оплату и подтвердит заказ.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Не удалось отправить данные админу: {e}")
        await message.answer("❌ Не удалось отправить данные. Пожалуйста, свяжитесь с поддержкой.", parse_mode="HTML")

    user_carts.pop(message.from_user.id, None)
    await state.clear()
    is_admin = (message.from_user.id == ADMIN_USER_ID)
    await message.answer("🙏 Спасибо за заказ! 🍕", reply_markup=main_menu(is_admin=is_admin), parse_mode="HTML")


@dp.message(F.text == "ℹ️ О нас / Доставка")
async def about(message: types.Message):
    await message.answer(
        "<b>🍕 Pizza_Store39</b>\n\n"
        "📍 Адрес: г. Калининград, ул. Дм. Донского, 39\n"
        "🕒 Работаем: ежедневно с 10:00 до 23:00\n\n"
        "<b>🚚 Доставка:</b>\n"
        "• Доставка: 150₽\n"
        "• Бесплатно при заказе от 800₽\n"
        "• Время: 30–60 минут\n\n"
        "📞 Поддержка: <b>+7 (952) 114-87-67</b>",
        parse_mode="HTML"
    )


@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id == ADMIN_USER_ID:
        await message.answer("🔐 <b>Админка:</b>", reply_markup=admin_keyboard(), parse_mode="HTML")
    else:
        await message.answer("❌ Доступ запрещён.", parse_mode="HTML")


@dp.callback_query(F.data == "admin_orders")
async def admin_show_orders(callback: types.CallbackQuery):
    all_orders = await get_all_orders(20)
    active_orders = [order for order in all_orders if order["status"] not in ('done', 'cancelled')]

    if not active_orders:
        await callback.message.answer("📭 Нет активных заказов.", parse_mode="HTML")
        await callback.answer()
        return

    keyboard = []
    for order in active_orders:
        status_emoji = {"new": "🆕", "cooking": "🍳", "delivery": "🚚", "done": "✅", "cancelled": "❌"}.get(order['status'], "❓")
        btn_text = f"{status_emoji} Заказ #{order['id']} ({order['total']}₽)"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_order_{order['id']}")])
    
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await callback.message.answer("📦 <b>Активные заказы:</b>", reply_markup=reply_markup, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_order_"))
async def show_admin_order_details(callback: types.CallbackQuery):
    try:
        order_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Неверный ID заказа.", show_alert=True)
        return

    from database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, items, total, address, phone, payment_method, status, created_at FROM orders WHERE id = $1",
            order_id
        )
    
    if not row:
        await callback.message.answer(f"❌ Заказ #{order_id} не найден.")
        return

    items = json.loads(row["items"]) if row["items"] else []
    status_map = {
        "new": "🆕 Новый",
        "cooking": "🍳 Готовится",
        "delivery": "🚚 Доставляется",
        "done": "✅ Завершён",
        "cancelled": "❌ Отменён"
    }
    status_text = status_map.get(row["status"], row["status"])
    created_at_str = row["created_at"].strftime('%d.%m.%Y %H:%M')

    try:
        user = await bot.get_chat(row["user_id"])
        user_name = user.full_name
    except:
        user_name = f"ID: {row['user_id']}"

    text = (
        f"📋 <b>Заказ #{row['id']}</b>\n\n"
        f"👤 Пользователь: {user_name}\n"
        f"📞 Телефон: {row['phone']}\n"
        f"📍 Адрес: {row['address']}\n"
        f"💳 Оплата: {row['payment_method']}\n"
        f"🔄 Статус: {status_text}\n"
        f"🕗 Время: {created_at_str}\n"
        f"💰 Итого: {row['total']}₽\n\n"
        f"<b>Состав:</b>\n"
    )
    for item in items:
        text += f"• {item.get('name', '—')} ×{item.get('quantity', 1)}\n"

    await callback.message.edit_text(text, reply_markup=order_status_buttons(row['id'], row['status']), parse_mode="HTML")


@dp.callback_query(F.data.startswith("status_"))
async def admin_update_order_status(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        action = parts[1]
        order_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка обработки команды.", show_alert=True)
        return

    new_status = "cancelled" if action == "cancel" else action
    user_id = await update_order_status(order_id, new_status)

    if user_id:
        status_messages = {
            "cooking": "пицца уже в печи! 🍕",
            "delivery": "курьер выехал к вам! 🚚",
            "done": "заказ завершён. Спасибо! ✅",
            "cancelled": "заказ отменён. Извините за неудобства."
        }
        msg = status_messages.get(action, f"статус изменён на '{new_status}'")
        try:
            await bot.send_message(user_id, f"🔄 Статус заказа обновлён: {msg}", parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

    status_labels = {"cooking": "готовится", "delivery": "выехал", "done": "завершён", "cancel": "отменён"}
    await callback.answer(f"✅ Статус обновлён на '{status_labels.get(action, action)}'")
    await callback.message.edit_reply_markup(reply_markup=order_status_buttons(order_id, new_status))


# === ON STARTUP / SHUTDOWN ===
async def on_startup(app):
    logger.info("🚀 Запуск бота...")
    logger.info(f"RENDER_EXTERNAL_URL = {os.getenv('RENDER_EXTERNAL_URL')}")
    logger.info(f"DATABASE_URL задан: {'Да' if os.getenv('DATABASE_URL') else 'Нет'}")
    
    await init_db()
    asyncio.create_task(cleanup_old_orders())
    
    WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")
    if not WEBHOOK_HOST:
        logger.error("❌ Переменная RENDER_EXTERNAL_URL не установлена!")
        return

    webhook_url = f"{WEBHOOK_HOST}/webhook/{BOT_TOKEN}"
    await bot.set_webhook(webhook_url)
    logger.info(f"✅ Вебхук установлен: {webhook_url}")


async def on_shutdown(app):
    logger.info("🛑 Завершение работы бота...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка при завершении: {e}")
    logger.info("✅ Бот остановлен.")


# === MAIN ===
def main():
    app = web.Application()
    webhook_path = f"/webhook/{BOT_TOKEN}"
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)
    port = int(os.getenv("PORT", 8000))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()