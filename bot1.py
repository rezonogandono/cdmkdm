import logging
from telegram import Update
import random
import string
import re
import sqlite3
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ======================= НАСТРОЙКИ =========================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8575320671:AAHsu5bEwPEN-PWTCzZwRA39TmGMJt2GW4E"
MAIN_ADMIN_ID = 7776826853
SUPPORT_USERNAME = "Pragma"
LEGACY_ADMIN_IDS = []
NOTIFICATION_CHAT_ID = -1003312996370

IMAGE_TYPES = {
    "main_menu": "Главное меню",
    "create": "Создать сделку",
}

# Состояния
(
    WAITING_FOR_AMOUNT,
    WAITING_FOR_DESCRIPTION
) = range(1, 3)

DB_NAME = "elf_otc_bot.db"

# ================= БАЗА ДАННЫХ И МЕНЕДЖЕР =================
class DatabaseManager:
    def __init__(self, db_name):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        try:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()

                cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    language TEXT DEFAULT 'ru',
                    completed_deals INTEGER DEFAULT 0
                )
                ''')

                cursor.execute('''
                CREATE TABLE IF NOT EXISTS deals (
                    deal_id TEXT PRIMARY KEY,
                    creator_id INTEGER,
                    buyer_id INTEGER,
                    creator_username TEXT,
                    buyer_username TEXT,
                    amount REAL NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    payment_method TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                ''')

                cursor.execute('''
                CREATE TABLE IF NOT EXISTS deal_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT,
                    creator_id INTEGER,
                    buyer_id INTEGER,
                    creator_username TEXT,
                    buyer_username TEXT,
                    deal_description TEXT,
                    status TEXT
                )
                ''')

                cursor.execute('''
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_type TEXT NOT NULL UNIQUE,
                    file_id TEXT NOT NULL
                )
                ''')

                cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY
                )
                ''')

                cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))

                for aid in LEGACY_ADMIN_IDS:
                    try:
                        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (aid,))
                    except Exception:
                        pass

                conn.commit()
                logger.info("Database initialized (tables preserved)")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")

    def _execute_query(self, query, params=(), commit=False):
        try:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if commit:
                    conn.commit()
                return cursor
        except Exception as e:
            logger.error(f"Database error: {e}")
            return None

    def get_image(self, image_type):
        cursor = self._execute_query("SELECT file_id FROM images WHERE image_type = ?", (image_type,))
        result = cursor.fetchone() if cursor else None
        return result[0] if result else None

    def save_image(self, image_type, file_id):
        return self._execute_query(
            "INSERT OR REPLACE INTO images (image_type, file_id) VALUES (?, ?)",
            (image_type, file_id), commit=True
        ) is not None

    def get_user(self, user_id):
        cursor = self._execute_query("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() if cursor else None

    def create_user(self, user_id):
        return self._execute_query(
            "INSERT INTO users (user_id) VALUES (?)", (user_id,), commit=True
        ) is not None

    def update_user(self, user_id, **fields):
        if not fields:
            return True
        set_clause = ", ".join([f"{key} = ?" for key in fields])
        values = list(fields.values())
        values.append(user_id)
        return self._execute_query(
            f"UPDATE users SET {set_clause} WHERE user_id = ?",
            tuple(values), commit=True
        ) is not None

    def is_admin(self, user_id: int) -> bool:
        if user_id == MAIN_ADMIN_ID:
            return True
        cursor = self._execute_query("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None if cursor else False

    def add_admin(self, user_id: int) -> bool:
        return self._execute_query(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,), commit=True
        ) is not None

    def remove_admin(self, user_id: int) -> bool:
        if user_id == MAIN_ADMIN_ID:
            return False
        return self._execute_query(
        "DELETE FROM admins WHERE user_id = ?", (user_id,), commit=True
        ) is not None

    def create_deal(self, deal_id, creator_id, creator_username, amount, description, payment_method):
        return self._execute_query(
            '''INSERT INTO deals 
               (deal_id, creator_id, creator_username, amount, description, payment_method) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (deal_id, creator_id, creator_username, amount, description, payment_method), commit=True
        ) is not None

    def get_deal(self, deal_id):
        cursor = self._execute_query("SELECT * FROM deals WHERE deal_id = ?", (deal_id,))
        return cursor.fetchone() if cursor else None

    def set_deal_buyer(self, deal_id, buyer_id, buyer_username):
        return self._execute_query(
            "UPDATE deals SET buyer_id = ?, buyer_username = ? WHERE deal_id = ?",
            (buyer_id, buyer_username, deal_id), commit=True
        ) is not None

    def cancel_deal(self, deal_id):
        deal = self.get_deal(deal_id)
        if not deal:
            return False
        success = self._execute_query(
            "UPDATE deals SET status = 'canceled' WHERE deal_id = ?",
            (deal_id,), commit=True
        ) is not None
        if success:
            self._execute_query(
                '''INSERT INTO deal_history 
                   (deal_id, creator_id, buyer_id, creator_username, buyer_username, 
                    deal_description, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (deal_id, deal[1], deal[2], deal[3], deal[4], deal[6], 'canceled'), commit=True
            )
        return success

    def complete_deal(self, deal_id):
        deal = self.get_deal(deal_id)
        if not deal:
            return False
        success = self._execute_query(
            "UPDATE deals SET status = 'completed' WHERE deal_id = ?",
            (deal_id,), commit=True
        ) is not None
        if success:
            self._execute_query(
                '''INSERT INTO deal_history 
                   (deal_id, creator_id, buyer_id, creator_username, buyer_username, 
                    deal_description, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (deal_id, deal[1], deal[2], deal[3], deal[4], deal[6], 'completed'), commit=True
            )
            creator_id = deal[1]
            user = self.get_user(creator_id)
            completed_deals = (user[2] if user and len(user) > 2 else 0) + 1
            self.update_user(creator_id, completed_deals=completed_deals)
        return success


db_manager = DatabaseManager(DB_NAME)

# ======================= ПЕРЕВОДЫ ==========================
TRANSLATIONS = {
    'main_menu': {'ru': "Добро пожаловать в Telegram NFT Transfer – надежную P2P платформу для обхода 21-дневной блокировки подарка после покупки с раздела Telegram Gifts",
                  'en': "Welcome to Telegram NFT Transfer – a reliable P2P platform for bypassing the 21-day lock after purchase with the Telegram Gifts section"},
    'create': {'ru': "💵 Создать сделку", 'en': "💵 Create a deal"},
    'language': {'ru': "🌐Сменить язык", 'en': "🌐Сhange language"},
    'support': {'ru': "📞 Поддержка", 'en': "📞 Support"},
    'back_to_menu': {'ru': "Вернуться в меню", 'en': "Back to menu"},
    'cancel_deal_title': {'ru': "Вы уверены, что хотите отменить сделку",
                          'en': "Are you sure you want to cancel the deal"},
    'cancel_warning': {'ru': "Это действие нельзя будет отменить.", 'en': "This action cannot be undone."},
    'yes_cancel': {'ru': "Да, отменить", 'en': "Yes, cancel"},
    'no': {'ru': "Нет", 'en': "No"},
    'deal_canceled': {'ru': "была отменена.", 'en': "has been canceled."},
    'back_to_menu_button': {'ru': "Вернуться в меню", 'en': "Back to menu"},
    'gift_link_error': {'ru': " Нужна ссылка на подарок!", 'en': " Need a gift link!"},
    'gift_link_example': {'ru': "Пример: https://t.me/nft/KissedFrog-1141",
                          'en': "Example: https://t.me/nft/KissedFrog-1141"},
    'deal_not_found': {'ru': "❌ Сделка не найдена или уже завершена", 'en': "❌ Deal not found or already completed"},
    'buyer_joined_title': {'ru': "👤 Покупатель присоединился к сделке", 'en': "👤 Buyer joined the deal"},
    'buyer_joined': {'ru': "⚠️Ожидайте оплату со стороны покупателя", 'en': "⚠️Wait for payment from the buyer"},
    'deal_for_buyer': {'ru': "🛒 Вы вошли в сделку", 'en': "🛒 You have joined the deal"},
    'deal_details': {'ru': "Детали сделки:", 'en': "Deal details:"},
    'deal_id_label': {'ru': "ID сделки:", 'en': "Deal ID:"},
    'amount_label': {'ru': "Сумма:", 'en': "Amount:"},
    'description_label': {'ru': "Описание:", 'en': "Description:"},
    'confirm_payment': {'ru': "✅ Подтвердить оплату", 'en': "✅ Confirm Payment"},
    'leave_deal': {'ru': "🚪 Покинуть сделку", 'en': "🚪 Leave Deal"},
    'payment_confirmed_title': {'ru': "✅ Оплата подтверждена", 'en': "✅ Payment Confirmed"},
    'payment_confirmed_buyer': {'ru': "Вы успешно подтвердили оплату!",
                                'en': "You have successfully confirmed the payment!"},
    'payment_confirmed_creator': {'ru': "Покупатель подтвердил оплату!", 'en': "The buyer has confirmed the payment!"},
    'deal_left_title': {'ru': "🚪 Вы покинули сделку", 'en': "🚪 You left the deal"},
    'deal_left_buyer': {'ru': "Вы успешно вышли из сделки.", 'en': "You have successfully left the deal."},
    'deal_left_creator': {'ru': "Покупатель покинул сделку.", 'en': "The buyer has left the deal."},
    'buyer_left': {'ru': "Покупатель покинул сделку", 'en': "Buyer left the deal"},
    'currency_not_sent': {
        'ru': f"🖋️ Напишите нашему Администратору для получения реквизитов (@Pragmatic_Support)",
        'en': f"️🖋️ Write to our Administrator to receive the details (@Pragmatic_Support)"},
    'payment_confirmed_details': {
        'ru': "Оплата по сделке #{deal_id} подтверждена.\nСумма: {amount} {currency}\nОписание: {description}",
        'en': "Payment for deal #{deal_id} confirmed.\nAmount: {amount} {currency}\nDescription: {description}"},
    'buyer_waiting': {'ru': "⌛Ожидайте, пока продавец отправит товар",
                      'en': "⌛Wait for the seller to send the goods"},
    'seller_waiting': {'ru': "Средства будут переведены на ваши реквизиты после .",
                       'en': "Funds will be transferred to your account after verification."},
    'admin_confirmation': {'ru': "✅ Сделка #{deal_id} успешно подтверждена!",
                           'en': "✅ Deal #{deal_id} successfully confirmed!"},
    'completed_deals': {'ru': "Завершенных сделок:", 'en': "Completed deals:"},
    'buyer_completed_deals': {'ru': "Количество завершенных сделок покупателя:", 'en': "Buyer's completed deals:"},
    'seller_completed_deals': {'ru': "🏆 Завершённых сделок у продавца:", 'en': "🏆 Seller's completed deals:"},
    'deal_canceled_by_creator': {'ru': "❌ Создатель отменил сделку", 'en': "❌ Creator canceled the deal"},
    'return_to_main_menu': {'ru': "Возвращаем вас в главное меню", 'en': "Returning you to the main menu"},
}


def get_translation(user_id, key):
    user = db_manager.get_user(user_id)
    lang = user[1] if user else 'ru'
    return TRANSLATIONS[key][lang]


# ================== ВСПОМОГАТЕЛЬНЫЕ ===================
def get_currency_name(payment_method, lang='ru'):
    return "Stars"

def format_deal_date(created_at):
    if not created_at:
        return "Дата не указана"
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return created_at.split()[0] if ' ' in created_at else created_at

def generate_deal_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))

def is_valid_link(text):
    LINK_REGEX = re.compile(
        r'^(?:http|https)://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(LINK_REGEX.match(text))

async def delete_previous_message(update: Update):
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except BadRequest:
            pass

# ============ ОБНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ ИЗОБРАЖЕНИЙ ============
async def send_message_with_image(update, context, chat_id, image_type, text, keyboard=None):
    file_id = db_manager.get_image(image_type)
    await delete_previous_message(update)
    parse_mode = 'HTML' if image_type == "main_menu" else None

    try:
        if file_id:
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )
                return True
            except Exception as photo_error:
                logger.warning(f"File_id не работает, отправляем только текст: {photo_error}")
                # Если file_id не работает, отправляем только текст
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )
                return True
        else:
            # Если file_id нет в базе, отправляем только текст
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode
            )
            return True
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False

async def send_confirmation_notification(context: ContextTypes.DEFAULT_TYPE, deal):
    deal_id = deal[0]
    creator_id = deal[1]
    buyer_id = deal[2]
    creator_username = deal[3] or f"ID:{creator_id}"
    buyer_username = deal[4] or f"ID:{buyer_id}"
    amount = deal[5]
    description = deal[6]
    payment_method = deal[8]
    created_at = deal[9]
    currency_name = get_currency_name(payment_method, 'ru')
    confirmed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    message = (
        f"✅ <b>Stars Deal</b>\n\n"
        f"🆔 <b>ID сделки</b>: <code>{deal_id}</code>\n"
        f"👤 <b>Создатель</b>: @{creator_username} (ID: {creator_id})\n"
        f"👥 <b>Покупатель</b>: @{buyer_username} (ID: {buyer_id})\n"
        f"💰 <b>Сумма</b>: {amount} {currency_name}\n"
        f"🎁 <b>Подарок</b>: {description}\n"
        f"🕒 Создана: {format_deal_date(created_at)}\n"
        f"🕒 Подтверждена: {confirmed_at}"
    )

    try:
        await context.bot.send_message(
            chat_id=NOTIFICATION_CHAT_ID,
            text=message,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления о подтверждении: {e}")


# ======================= МЕНЮ ============================
def main_menu(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_translation(user_id, 'create'), callback_data="create")],
        [InlineKeyboardButton(get_translation(user_id, 'language'), callback_data="english")],
        [InlineKeyboardButton(get_translation(user_id, 'support'), url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])

def generate_main_menu_caption(user_id):
    user = db_manager.get_user(user_id)
    lang = user[1] if user else 'ru'
    if lang == 'ru':
        return (
            "<b>👋 Добро пожаловать в Transfer Deal Robot! 💼💰</b>\n"
            "<b> </b>\n"
            "<b>Вы попали в бот для честных, безопасных и прозрачных сделок на базе Transfer 🔐</b>\n"
            "<b>Наша цель — помочь пользователям проводить сделки на звезды без обмана, лишних рисков и недоверия 🤝</b>\n"
            "<b> </b>\n"
            "<b>🚀 Что вас ждёт в боте:</b>\n"
            "<b>🔹Чётко зафиксированные условия сделки </b>\n"
            "<b>🔹Защита звезд до полного выполнения договорённостей </b>\n"
            "<b>🔹Подтверждение действий обеими сторонами </b>\n"
            "<b> Минимум посредников — максимум доверия </b>\n"
            "<b> </b>\n"
            "<b>📌 Важно помнить: </b>\n"
            "<b>⚠️ Всегда следуйте инструкциям бота </b>\n"
            "<b>❌ Не отправляйте звезды вне системы </b>\n"
            "<b>💼Покупайте и продавайте всё, что угодно – безопасно!</b>\n"
            "<b>🛡 В случае спорных ситуаций работает поддержка </b>\n"
            "<b> </b>\n"
            "<b>С любовью и поддержкой Transfer! </b>\n"
            "<b> </b>\n"
            "<b>✨ Готовы начать безопасную сделку? </b>\n"
            "<b>Выберите нужное действие ниже и приступайте прямо сейчас  </b>\n"
            "<b>👇👇 </b>\n"
        )
    else:
        return (
            "<b>Welcome to Telegram NFT Transfer – a reliable P2P platform for bypassing the 21-day lock after purchase with the Telegram Gifts section</b>\n"
            "<b>💼Buy and sell anything you want - safely!</b>\n"
            "From Telegram gifts and NFTs to tokens, transactions are easy and risk-free."
        )

def buyer_deal_menu(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_translation(user_id, 'confirm_payment'), callback_data="confirm_payment"),
            InlineKeyboardButton(get_translation(user_id, 'leave_deal'), callback_data="leave_deal")
        ]
    ])

def generate_buyer_deal_caption(deal_id, amount, description, payment_method, created_at, seller_completed: int,
                                lang='ru'):
    currency = get_currency_name(payment_method, lang)
    deal_date = format_deal_date(created_at)
    base = (
        f"<b>✅ Вы вошли в сделку!</b>\n"
        f"#{deal_id}\n"
        f"💰 <b>Сумма</b>: {amount} {currency}\n"
        f"📜 <b>Подарок</b>: {description}\n"
        f"⏰ <b>Дата</b>: {deal_date}\n"
        f"🖋️ <b>Напишите нашему Администратору для получения реквизитов</b> @{SUPPORT_USERNAME}"
    )
    seller_line = f"\n{TRANSLATIONS['seller_completed_deals'][lang]} {seller_completed}"
    return base + seller_line


# ========================= ОСНОВНОЕ =========================
async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not db_manager.get_user(user.id):
        db_manager.create_user(user.id)

    if context.args and context.args[0].startswith('deal_'):
        deal_id = context.args[0][5:]
        await join_deal_as_buyer(update, context, deal_id)
    else:
        await send_main_menu(update, context)

async def join_deal_as_buyer(update: Update, context: CallbackContext, deal_id: str):
    user = update.effective_user
    deal = db_manager.get_deal(deal_id)
    if not deal or len(deal) < 10 or deal[7] == 'canceled':
        caption = get_translation(user.id, 'deal_not_found')
        await context.bot.send_message(chat_id=update.effective_chat.id, text=caption, reply_markup=main_menu(user.id))
        return

    buyer_username = user.username or f"ID:{user.id}"
    db_manager.set_deal_buyer(deal_id, user.id, buyer_username)

    await notify_creator_about_buyer(update, context, deal[1], deal_id, user.id)
    await show_buyer_deal(update, context, deal_id, deal[5], deal[6], deal[8], deal[9])

async def notify_creator_about_buyer(update: Update, context: CallbackContext, creator_id: int, deal_id: str,
                                     buyer_id: int):
    lang = "ru"
    user_data = db_manager.get_user(creator_id)
    if user_data:
        lang = user_data[1]
    buyer_data = db_manager.get_user(buyer_id)
    completed_deals = buyer_data[2] if buyer_data and len(buyer_data) > 2 else 0
    caption = (
        f"<b>👤 Покупатель присоединился к сделке #{deal_id}</b>\n\n"
        f"{get_translation(creator_id, 'buyer_joined')}\n\n"
        f"{get_translation(creator_id, 'buyer_completed_deals')} {completed_deals}"
    )
    try:
        await context.bot.send_message(chat_id=creator_id, text=caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления создателю: {e}")

async def show_buyer_deal(update: Update, context: CallbackContext, deal_id: str, amount: float, description: str,
                          payment_method: str, created_at: str):
    user = update.effective_user
    lang = "ru"
    user_data = db_manager.get_user(user.id)
    if user_data:
        lang = user_data[1]

    deal = db_manager.get_deal(deal_id)
    seller_completed = 0
    if deal:
        creator_id = deal[1]
        creator_data = db_manager.get_user(creator_id)
        if creator_data and len(creator_data) > 2:
            seller_completed = creator_data[2] or 0

    caption = generate_buyer_deal_caption(deal_id, amount, description, payment_method, created_at, seller_completed,
                                          lang)
    keyboard = buyer_deal_menu(user.id)

    context.user_data['current_deal'] = deal_id
    await delete_previous_message(update)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def send_main_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    caption = generate_main_menu_caption(user.id)
    keyboard = main_menu(user.id)
    context.user_data.pop('current_deal', None)
    await send_message_with_image(update, context, update.effective_chat.id, "main_menu", caption, keyboard)


# ========== ЭКРАНЫ ДЛЯ СОЗДАТЕЛЯ СДЕЛКИ ==========
async def send_amount_input(update: Update, context: CallbackContext):
    user = update.effective_user
    lang = "ru"
    user_data = db_manager.get_user(user.id)
    if user_data:
        lang = user_data[1]
    caption = (
        f"💼 Создание сделки\nВведите сумму Stars сделки в формате: 100.5"
        if lang == 'ru' else
        f"💼 Create deal\nEnter Stars deal amount in format: 100.5"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔙 {get_translation(user.id, 'back_to_menu')}", callback_data="back_main")]
    ])
    await send_message_with_image(update, context, update.effective_chat.id, "create", caption, keyboard)
    context.user_data['waiting_for'] = 'amount'

async def send_description_input(update: Update, context: CallbackContext, amount: float):
    user = update.effective_user
    lang = "ru"
    user_data = db_manager.get_user(user.id)
    if user_data:
        lang = user_data[1]
    caption = (
        f"📝 Укажите, что вы предлагаете в этой сделке за {amount} Stars\n\nПример: https://t.me/nft/KissedFrog-1141"
        if lang == 'ru' else
        f"📝 Specify what you are offering in this deal for {amount} Stars\n\nExample: https://t.me/nft/KissedFrog-1141"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔙 {get_translation(user.id, 'back_to_menu_button')}", callback_data="back_main")]
    ])
    await delete_previous_message(update)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=caption, reply_markup=keyboard)
    context.user_data['deal_amount'] = amount
    context.user_data['waiting_for'] = 'description'

async def confirm_deal(update: Update, context: CallbackContext, description: str):
    user = update.effective_user
    amount = context.user_data.get('deal_amount', 0.0)
    deal_id = generate_deal_id()
    creator_username = user.username or f"ID:{user.id}"
    db_manager.create_deal(deal_id, user.id, creator_username, amount, description, "stars")

    lang = "ru"
    user_data = db_manager.get_user(user.id)
    if user_data:
        lang = user_data[1]
    if lang == 'ru':
        caption = (
            f"<b>✅ Сделка #{deal_id} успешно создана!</b>\n\n"
            f"💰 <b>Сумма</b>: {amount} Stars\n"
            f"📜 <b>Описание</b>: {description}\n"
            f"🔗 <b>Ссылка для покупателя</b>:\n"
            f"https://t.me/TransferMetaRobot?start=deal_{deal_id}\n\n"
        )
    else:
        caption = (
            f"<b>✅ Deal #{deal_id} successfully created!</b>\n\n"
            f"💰 <b>Amount</b>: {amount} Stars\n"
            f"📜 <b>Description</b>: {description}\n"
            f"🔗 <b>Link for buyer</b>:\n"
            f"https://t.me/TransferMetaRobot?start=deal_{deal_id}\n\n"
        )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✕ Отменить сделку" if lang == 'ru' else "✕ Cancel deal",
                              callback_data=f"cancel_deal:{deal_id}")]
    ])
    await delete_previous_message(update)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    for key in ['deal_amount', 'waiting_for']:
        context.user_data.pop(key, None)

async def send_cancel_confirmation(update: Update, context: CallbackContext, deal_id: str):
    user = update.effective_user
    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
    caption = (
        f"<b>Вы уверены, что хотите отменить сделку #{deal_id}?</b>\n\n"
        f"{get_translation(user.id, 'cancel_warning')}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Да, отменить" if lang == 'ru' else "Yes, cancel",
                              callback_data=f"confirm_cancel:{deal_id}")],
        [InlineKeyboardButton("Нет" if lang == 'ru' else "No", callback_data=f"cancel_cancel:{deal_id}")]
    ])
    try:
        await update.callback_query.message.edit_text(
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except BadRequest as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

async def send_deal_canceled(update: Update, context: CallbackContext, deal_id: str):
    user = update.effective_user
    deal = db_manager.get_deal(deal_id)
    db_manager.cancel_deal(deal_id)
    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'

    caption = f"<b>✅ Сделка #{deal_id} была отменена.</b>"
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=caption,
        parse_mode="HTML"
    )

    if deal and deal[2]:
        buyer_id = deal[2]
        buyer_caption = (
            f"<b>❌ Создатель отменил сделку #{deal_id}</b>\n\n"
            f"{get_translation(buyer_id, 'return_to_main_menu')}"
        )
        try:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=buyer_caption,
                parse_mode="HTML"
            )
            await send_main_menu_for_user(context, buyer_id)
        except Exception as e:
            logger.error(f"Ошибка при уведомлении покупателя: {e}")

    await send_main_menu(update, context)

async def send_main_menu_for_user(context: CallbackContext, user_id: int):
    caption = generate_main_menu_caption(user_id)
    keyboard = main_menu(user_id)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки главного меню: {e}")


# ================= КНОПКИ/КОЛЛБЭКИ =================
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    handlers = {
        "create": send_amount_input,
        "english": handle_language_change,
        "back_main": send_main_menu,
        "confirm_payment": handle_payment_confirmation,
        "leave_deal": handle_buyer_leave
    }

    if data.startswith("cancel_deal:"):
        deal_id = data.split(":")[1]
        await send_cancel_confirmation(update, context, deal_id)
    elif data.startswith("confirm_cancel:"):
        deal_id = data.split(":")[1]
        await send_deal_canceled(update, context, deal_id)
    elif data.startswith("cancel_cancel:"):
        deal_id = data.split(":")[1]
        await handle_cancel_cancel(update, context, deal_id)
    elif data in handlers:
        await handlers[data](update, context)

async def handle_language_change(update: Update, context: CallbackContext):
    user = update.effective_user
    current_lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
    new_lang = 'en' if current_lang == 'ru' else 'ru'
    db_manager.update_user(user.id, language=new_lang)
    await send_main_menu(update, context)

async def handle_cancel_cancel(update: Update, context: CallbackContext, deal_id: str):
    user = update.effective_user
    deal = db_manager.get_deal(deal_id)
    if not deal:
        return
    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
    amount, description, payment_method = deal[5], deal[6], deal[8]
    caption = (
        f"<b>✅ Сделка #{deal_id}</b>\n\n"
        f"💰 <b>Сумма</b>: {amount} Stars\n"
        f"📜 <b>Описание</b>: {description}\n"
        f"🔗 <b>Ссылка для покупателя</b>:\nhttps://t.me/TransferMetaRobot?start=deal_{deal_id}\n\n"
        if lang == 'ru' else
        f"<b>✅ Deal #{deal_id}</b>\n\n"
        f"💰 <b>Amount</b>: {amount} Stars\n"
        f"📜 <b>Description</b>: {description}\n"
        f"🔗 <b>Link for buyer</b>:\nhttps://t.me/TransferMetaRobot?start=deal_{deal_id}\n\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✕ Отменить сделку" if lang == 'ru' else "✕ Cancel deal",
                              callback_data=f"cancel_deal:{deal_id}")]
    ])
    await update.callback_query.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# ================= ПЛАТЁЖ И ВЫХОД ПОКУПАТЕЛЯ ==============
async def handle_payment_confirmation(update: Update, context: CallbackContext):
    user = update.effective_user
    deal_id = context.user_data.get('current_deal', '')
    if not deal_id:
        await send_main_menu(update, context)
        return
    deal = db_manager.get_deal(deal_id)
    if not deal:
        caption = get_translation(user.id, 'deal_not_found')
        await context.bot.send_message(chat_id=update.effective_chat.id, text=caption)
        await send_main_menu(update, context)
        return
    message = get_translation(user.id, 'currency_not_sent')
    await context.bot.send_message(chat_id=update.effective_chat.id, text=message)

    amount, description, payment_method, created_at = deal[5], deal[6], deal[8], deal[9]
    seller_completed = 0
    creator_data = db_manager.get_user(deal[1])
    if creator_data and len(creator_data) > 2:
        seller_completed = creator_data[2] or 0
    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
    caption = generate_buyer_deal_caption(deal_id, amount, description, payment_method, created_at, seller_completed,
                                          lang)
    keyboard = buyer_deal_menu(user.id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def handle_buyer_leave(update: Update, context: CallbackContext):
    user = update.effective_user
    deal_id = context.user_data.get('current_deal', '')
    if not deal_id:
        await send_main_menu(update, context)
        return
    deal = db_manager.get_deal(deal_id)
    if not deal:
        caption = get_translation(user.id, 'deal_not_found')
        await context.bot.send_message(chat_id=update.effective_chat.id, text=caption)
        await send_main_menu(update, context)
        return
    creator_id = deal[1]
    db_manager.set_deal_buyer(deal_id, None, None)
    await notify_buyer_about_leave(update, context, user.id, deal_id)
    await notify_creator_about_leave(update, context, creator_id, deal_id)
    await send_main_menu(update, context)

async def notify_buyer_about_leave(update: Update, context: CallbackContext, buyer_id: int, deal_id: str):
    lang = db_manager.get_user(buyer_id)[1] if db_manager.get_user(buyer_id) else 'ru'
    caption = (
        f"<b>{get_translation(buyer_id, 'deal_left_title')} #{deal_id}</b>\n\n"
        f"{get_translation(buyer_id, 'deal_left_buyer')}"
    )
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text=caption,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления покупателю: {e}")

async def notify_creator_about_leave(update: Update, context: CallbackContext, creator_id: int, deal_id: str):
    lang = db_manager.get_user(creator_id)[1] if db_manager.get_user(creator_id) else 'ru'
    caption = (
        f"<b>{get_translation(creator_id, 'buyer_left')} #{deal_id}</b>\n\n"
        f"{get_translation(creator_id, 'deal_left_creator')}"
    )
    try:
        await context.bot.send_message(
            chat_id=creator_id,
            text=caption,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления создателю: {e}")


# ================== ОБРАБОТЧИК ВВОДА ТЕКСТА ================
async def handle_input(update: Update, context: CallbackContext):
    user = update.effective_user
    text = update.message.text
    input_type = context.user_data.get('waiting_for', '')
    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'

    handlers = {
        'amount': handle_amount_input,
        'description': handle_description_input
    }
    if input_type in handlers:
        await handlers[input_type](update, context, text, lang)
    else:
        error_text = "❌ Неизвестный запрос. Пожалуйста, используйте меню." if lang == 'ru' else "❌ Unknown request. Please use the menu."
        await context.bot.send_message(chat_id=update.effective_chat.id, text=error_text)
        await send_main_menu(update, context)

async def handle_amount_input(update: Update, context: CallbackContext, text: str, lang: str):
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        await send_description_input(update, context, amount)
    except ValueError:
        error_text = (
            f"❌ Некорректная сумма! Введите число в формате: 100.5 (Stars)"
            if lang == 'ru' else
            f"❌ Invalid amount! Enter a number in the format: 100.5 (Stars)"
        )
        await context.bot.send_message(chat_id=update.effective_chat.id, text=error_text)

async def handle_description_input(update: Update, context: CallbackContext, text: str, lang: str):
    amount = context.user_data.get('deal_amount', 0.0)
    if is_valid_link(text):
        await confirm_deal(update, context, text)
    else:
        error_text = get_translation(update.effective_user.id, 'gift_link_error')
        example_text = get_translation(update.effective_user.id, 'gift_link_example')
        caption = (
            f"❌ Ошибка при создании сделки на {amount} Stars\n\n{error_text}\n\n{example_text}"
            if lang == 'ru' else
            f"❌ Error creating deal for {amount} Stars\n\n{error_text}\n\n{example_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔙 {get_translation(update.effective_user.id, 'back_to_menu_button')}",
                                  callback_data="back_main")]
        ])
        await context.bot.send_message(chat_id=update.effective_chat.id, text=caption, reply_markup=keyboard)


# ===================== АДМИН ФУНКЦИИ ======================
async def set_image_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not db_manager.is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    args = context.args
    if not args or args[0] not in IMAGE_TYPES:
        image_types_list = "\n".join([f"/setimage {key} - {value}" for key, value in IMAGE_TYPES.items()])
        await update.message.reply_text(
            f"❌ Неверный формат команды. Используйте:\n{image_types_list}\n\nПосле команды отправьте изображение"
        )
        return
    image_type = args[0]
    context.user_data['waiting_for_image_type'] = image_type
    context.user_data['waiting_for'] = 'image'
    await update.message.reply_text(
        f"🖼️ Отправьте изображение для раздела: {IMAGE_TYPES[image_type]}\n"
        f"Изображение будет использоваться как фон для этого меню."
    )

async def handle_image(update: Update, context: CallbackContext):
    user = update.effective_user
    if not db_manager.is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав для загрузки изображений.")
        return
    if 'waiting_for_image_type' not in context.user_data:
        await update.message.reply_text("❌ Сначала выберите тип изображения с помощью /setimage <тип>")
        return
    image_type = context.user_data['waiting_for_image_type']
    try:
        photo = update.message.photo[-1]
    except Exception:
        await update.message.reply_text("❌ Не удалось получить фото. Отправьте изображение снова.")
        return
    file_id = photo.file_id
    if db_manager.save_image(image_type, file_id):
        await update.message.reply_text(f"✅ Изображение для '{IMAGE_TYPES[image_type]}' успешно установлено!")
    else:
        await update.message.reply_text("❌ Ошибка при сохранении изображения")
    context.user_data.pop('waiting_for_image_type', None)
    context.user_data.pop('waiting_for', None)

async def confirm_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not db_manager.is_admin(user.id):
        lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
        message = "❌ У вас нет прав для выполнения этой команды." if lang == 'ru' else "❌ You don't have permission."
        await update.message.reply_text(message)
        return
    args = context.args
    if not args:
        lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
        message = "ℹ️ Использование: /confirm <ID сделки>" if lang == 'ru' else "ℹ️ Usage: /confirm <deal ID>"
        await update.message.reply_text(message)
        return
    deal_id = args[0]
    deal = db_manager.get_deal(deal_id)
    if not deal:
        lang =\
                db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
        message = "❌ Сделка не найдена." if lang == 'ru' else "❌ Deal not found."
        await update.message.reply_text(message)
        return
    db_manager.complete_deal(deal_id)
    await notify_participants_about_confirmation(update, context, deal)
    await send_confirmation_notification(context, deal)

    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
    message = f"✅ Сделка #{deal_id} успешно подтверждена!" if lang == 'ru' else f"✅ Deal #{deal_id} successfully confirmed!"
    await update.message.reply_text(message)

async def set_deals_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not db_manager.is_admin(user.id):
        lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
        message = "❌ У вас нет прав для выполнения этой команды." if lang == 'ru' else "❌ You don't have permission."
        await update.message.reply_text(message)
        return
    args = context.args
    if not args or not args[0].isdigit():
        lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
        message = "ℹ️ Использование: /deals <количество> [user_id]" if lang == 'ru' else "ℹ️ Usage: /deals <number> [user_id]"
        await update.message.reply_text(message)
        return
    count = int(args[0])
    target_id = user.id
    if len(args) >= 2 and args[1].isdigit():
        target_id = int(args[1])
        if not db_manager.get_user(target_id):
            db_manager.create_user(target_id)
    db_manager.update_user(target_id, completed_deals=count)
    lang = db_manager.get_user(user.id)[1] if db_manager.get_user(user.id) else 'ru'
    if target_id == user.id:
        msg = f"✅ Количество завершенных сделок установлено: {count}" if lang == 'ru' else f"✅ Completed deals count set to: {count}"
    else:
        msg = f"✅ Пользователю {target_id} установлено завершенных сделок: {count}" if lang == 'ru' else f"✅ Set completed deals for {target_id}: {count}"
    await update.message.reply_text(msg)
    await send_main_menu(update, context)

async def add_admin_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id != MAIN_ADMIN_ID:
        await update.message.reply_text("⛔ Только главный админ может добавлять админов")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("ℹ️ Использование: /addadmin <user_id>")
        return
    new_admin_id = int(args[0])
    db_manager.add_admin(new_admin_id)
    await update.message.reply_text(f"✅ Пользователь {new_admin_id} добавлен в администраторы")
    try:
        await context.bot.send_message(chat_id=new_admin_id, text="✅ Вы получили права администратора в боте.")
    except Exception:
        pass
    try:
        await context.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=f"🔔 Добавлен администратор: {new_admin_id}")
    except Exception:
        pass

async def remove_admin_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id != MAIN_ADMIN_ID:
        await update.message.reply_text("⛔ Только главный админ может удалять админов")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("ℹ️ Использование: /removeadmin <user_id>")
        return
    remove_id = int(args[0])
    if remove_id == MAIN_ADMIN_ID:
        await update.message.reply_text("⚠ Нельзя удалить главного админа")
        return
    db_manager.remove_admin(remove_id)
    await update.message.reply_text(f"❌ Пользователь {remove_id} удалён из администраторов")
    try:
        await context.bot.send_message(chat_id=remove_id, text="❌ Ваши права администратора были отозваны.")
    except Exception:
        pass
    try:
        await context.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=f"🔔 Удалён администратор: {remove_id}")
    except Exception:
        pass

# ============== ПОДТВЕРЖДЕНИЕ СДЕЛКИ (уведомления) ===============
async def notify_participants_about_confirmation(update: Update, context: CallbackContext, deal):
    deal_id = deal[0]
    creator_id = deal[1]
    buyer_id = deal[2] if len(deal) > 2 else None
    amount = deal[5]
    description = deal[6]  # Это ссылка на подарок
    payment_method = deal[8] if len(deal) > 8 else "stars"

    creator_lang = "ru"
    creator_data = db_manager.get_user(creator_id)
    if creator_data:
        creator_lang = creator_data[1]
    currency = get_currency_name(payment_method, creator_lang)

    # Уведомление для создателя сделки
    if creator_lang == 'ru':
        caption = (
            f"<b>✅ Оплата по сделке #{deal_id} подтверждена.</b>\n\n"
            f"💰 <b>Сумма</b>: {amount} {currency}\n"
            f"🎁 <b>Подарок</b>: {description}\n\n"
            f"🎁 <b>Отправьте подарок доверенному лицу</b>: @{SUPPORT_USERNAME}\n"
            f"⚠️<b>Отправьте подарок именно на аккаунт доверенного лица, иначе ваши средства могут быть утеряны!</b>"
        )
    else:
        caption = (
            f"<b>✅ Payment for deal #{deal_id} confirmed.</b>\n\n"
            f"💰 <b>Amount</b>: {amount} {currency}\n"
            f"🎁 <b>Gift</b>: {description}\n\n"
            f"🎁 <b>Send a gift to a trusted person</b>: @{SUPPORT_USERNAME}\n"
            f"⚠️<b>Send the gift to the account of a trusted person, otherwise your funds may be lost!</b>"
        )
    try:
        await context.bot.send_message(
            chat_id=creator_id,
            text=caption,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления создателю: {e}")

    # Уведомление для покупателя
    if buyer_id:
        buyer_lang = "ru"
        buyer_data = db_manager.get_user(buyer_id)
        if buyer_data:
            buyer_lang = buyer_data[1]
        currency = get_currency_name(payment_method, buyer_lang)
        caption_buyer = (
            f"<b>✅ Оплата по сделке #{deal_id} подтверждена.</b>\n\n"
            f"💰 <b>Сумма</b>: {amount} {currency}\n"
            f"🎁 <b>Подарок</b>: {description}\n\n"
            f"{get_translation(buyer_id, 'buyer_waiting')}"
            if buyer_lang == 'ru' else

            f"<b>✅ Payment for deal #{deal_id} confirmed.</b>\n\n"
            f"💰 <b>Amount</b>: {amount} {currency}\n"
            f"🎁 <b>Gift</b>: {description}\n\n"
            f"{get_translation(buyer_id, 'buyer_waiting')}"
        )
        try:
            await context.bot.send_message(
                chat_id=buyer_id,
                   text=caption_buyer,
                     parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления покупателю: {e}")


# ===================== РЕГИСТРАЦИЯ ХЕНДЛЕРОВ =====================
def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("confirm", confirm_command))
    application.add_handler(CommandHandler("deals", set_deals_command))
    application.add_handler(CommandHandler("setimage", set_image_command))
    application.add_handler(CommandHandler("addadmin", add_admin_command))
    application.add_handler(CommandHandler("removeadmin", remove_admin_command))

    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    logger.info("Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()