from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

def main_menu(is_admin: bool = False):
    keyboard = [
        [KeyboardButton(text="🍕 Меню пицц"), KeyboardButton(text="🥗 Салаты и закуски")],
        [KeyboardButton(text="🥤 Напитки"), KeyboardButton(text="🛒 Корзина")],
        [KeyboardButton(text="📍 Мои заказы"), KeyboardButton(text="ℹ️ О нас / Доставка")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="🔐 Админка")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отправить номер", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def product_buttons(product_id: str, price_small: int = None, price_large: int = None):
    keyboard = []
    if price_large is not None and price_small is not None:
        keyboard.append([
            InlineKeyboardButton(text=f"Маленькая ({price_small}₽)", callback_data=f"add_{product_id}_small"),
            InlineKeyboardButton(text=f"Большая ({price_large}₽)", callback_data=f"add_{product_id}_large")
        ])
    elif price_small is not None:
        keyboard.append([
            InlineKeyboardButton(text=f"Добавить в корзину ({price_small}₽)", callback_data=f"add_{product_id}_nosize")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def cart_item_buttons(item_key: str, quantity: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec_{item_key}"),
            InlineKeyboardButton(text=str(quantity), callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc_{item_key}")
        ],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cart_del_{item_key}")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_main")]
    ])


def cart_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_main")]
    ])


def payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Онлайн", callback_data="pay_online")],
        [InlineKeyboardButton(text="💵 Наличными", callback_data="pay_cash")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_cart")]
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Все заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])


def order_status_buttons(order_id: int, current_status: str = "new"):
    status_map = {
        "new": ["cooking", "cancelled"],
        "cooking": ["delivery", "done", "cancelled"],
        "delivery": ["done", "cancelled"],
        "done": [],
        "cancelled": []
    }
    available_transitions = status_map.get(current_status, [])

    buttons = []
    if "cooking" in available_transitions:
        buttons.append(InlineKeyboardButton(text="🍳 Готовится", callback_data=f"status_cooking_{order_id}"))
    if "delivery" in available_transitions:
        buttons.append(InlineKeyboardButton(text="🚚 Выехал", callback_data=f"status_delivery_{order_id}"))
    if "done" in available_transitions:
        buttons.append(InlineKeyboardButton(text="✅ Завершён", callback_data=f"status_done_{order_id}"))
    if "cancelled" in available_transitions:
        buttons.append(InlineKeyboardButton(text="❌ Отменить", callback_data=f"status_cancel_{order_id}"))

    keyboard = []
    for i in range(0, len(buttons), 2):
        keyboard.append(buttons[i:i+2])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_order_{order_id}")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


INGREDIENTS = {
    "tomato": ("Помидоры", 20),
    "cheese": ("Сыр моцарелла", 30),
    "ham": ("Ветчина", 40),
    "pepperoni": ("Пепперони", 45),
    "mushrooms": ("Шампиньоны", 25),
    "olives": ("Оливки", 20),
    "corn": ("Кукуруза", 15),
    "onion": ("Лук", 10),
    "cucumber": ("Огурцы", 15),
    "bacon": ("Бекон", 50),
    "chicken": ("Курица", 40),
    "salami": ("Салями", 45),
    "pineapple": ("Ананас", 20),
    "garlic_sauce": ("Чесночный соус", 15),
    "bbq_sauce": ("Соус барбекю", 15),
    "ketchup": ("Кетчуп", 10),
    "mayo": ("Майонез", 10),
    "parmesan": ("Пармезан", 35),
    "gorgonzola": ("Горгонзола", 50),
    "feta": ("Фета", 30)
}


def build_pizza_custom_keyboard(selected: dict, base_price: int, size: str):
    lines = []
    total_extra = 0
    ingredient_items = list(INGREDIENTS.items())
    for i in range(0, len(ingredient_items), 2):
        row = []
        for key, (name, price_per_50g) in ingredient_items[i:i+2]:
            grams = selected.get(key, 0)
            item_price = (grams // 50) * price_per_50g
            total_extra += item_price
            if grams > 0:
                row.append(InlineKeyboardButton(text=f"✅ {name} ({grams}г)", callback_data=f"custom_add_{key}"))
            else:
                row.append(InlineKeyboardButton(text=name, callback_data=f"custom_add_{key}"))
        lines.append(row)

    total = base_price + total_extra
    lines.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="custom_cancel"),
        InlineKeyboardButton(text=f"✅ Готово ({total}₽)", callback_data="custom_done")
    ])
    return InlineKeyboardMarkup(inline_keyboard=lines)