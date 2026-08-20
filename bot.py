import logging
import random
import string
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PicklePersistence
from telegram.error import Conflict, TimedOut, NetworkError

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

from config import *

BALANCES: dict = {}  # {user_id: {"RUB": 0.0, "TON": 0.0, "Stars": 0.0}}

# ── Функция для отправки логов в чат ───────────────────────────────────────
async def send_log_to_chat(context, message: str, icon: str = "📋"):
    try:
        await context.bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=f"{icon} <b>ЛОГ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{message}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить лог в чат: {e}")

# ── Функция для получения информации о пользователе (юзернейм + айди) ─────────
def get_user_info(user):
    username = f"@{user.username}" if user.username else "—"
    return f"{username} (ID: <code>{user.id}</code>)"

def build_log(user, title: str, lines: list[str]) -> str:
    user_info = get_user_info(user)
    body = "\n".join(lines).strip()
    if body:
        return f"{title}\n👤 {user_info}\n{body}"
    return f"{title}\n👤 {user_info}"

# ── Хранилище сделок {ref_code: {seller_id, buyer_id, amount, currency, description}} ──
DEALS: dict = {}

# ── Кастомные эмодзи (HTML-теги, parse_mode=HTML) ────────────────────────────
E_WAVE   = '<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji>'
E_BRIEF  = '<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji>'
E_SPARK  = '<tg-emoji emoji-id="5890925363067886150">✨</tg-emoji>'
E_CARD   = '<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji>'
E_SHIELD = '<tg-emoji emoji-id="6030445631921721471">🛡</tg-emoji>'
E_CART   = '<tg-emoji emoji-id="5278613311858959074">🛒</tg-emoji>'
E_BRIEF2 = '<tg-emoji emoji-id="5276037216244624892">💼</tg-emoji>'
E_FOLDER = '<tg-emoji emoji-id="5278227821364275264">📁</tg-emoji>'
E_CHART  = '<tg-emoji emoji-id="5278778882848220741">📊</tg-emoji>'
E_USERS  = '<tg-emoji emoji-id="5298668674532538341">👥</tg-emoji>'
E_MAIL   = '<tg-emoji emoji-id="5278589204207528856">📨</tg-emoji>'
E_DEV    = '<tg-emoji emoji-id="5276381204470329471">🧑‍💻</tg-emoji>'
E_SCREEN = '<tg-emoji emoji-id="5278647306525108244">🖥</tg-emoji>'
E_TEXT   = '<tg-emoji emoji-id="5242602592357345985">🔤</tg-emoji>'
E_LIGHT  = '⚡️'  # обычный Unicode


# ── Главное меню (кнопки) ────────────────────────────────────────────────────
# ── ID кастомных эмодзи для кнопок (icon_custom_emoji_id) ───────────────────
IC_CART   = "5278613311858959074"
IC_BRIEF  = "5276037216244624892"
IC_FOLDER = "5278227821364275264"
IC_CHART  = "5278778882848220741"
IC_USERS  = "5298668674532538341"
IC_MAIL   = "5278589204207528856"
IC_DEV    = "5276381204470329471"
IC_SCREEN = "5278647306525108244"
IC_TEXT   = "5242602592357345985"



async def _send_photo_or_text(query, text, parse_mode="HTML", reply_markup=None, photo_path=None, lang="ru"):
    if photo_path:
        # If photo_path is a dict, get the language-specific path
        current_photo_path = None
        if isinstance(photo_path, dict):
            # Попробуем нужный язык, потом русский, потом дефолтный
            current_photo_path = photo_path.get(lang)
            if not current_photo_path or not Path(current_photo_path).exists():
                current_photo_path = photo_path.get("ru")
            if not current_photo_path or not Path(current_photo_path).exists():
                current_photo_path = photo_path.get("default")
        else:
            current_photo_path = photo_path

        # Если нашли путь, попробуем открыть
        if current_photo_path and Path(current_photo_path).exists():
            try:
                with open(current_photo_path, "rb") as photo:
                    await query.message.reply_photo(photo=photo, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
                try:
                    await query.message.delete()
                except Exception:
                    pass
            except Exception:
                await query.message.reply_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            await query.message.reply_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        try:
            await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            pass

def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    labels = {
        "ru": {
            "deal":    "Создать сделку",
            "balance": "Мой баланс",
            "details": "Реквизиты",
            "channel": "Канал ↗",
            "refs":    "Рефералы",
            "tickets": "Обращения",
            "support": "Поддержка ↗",
            "miniapp": "Мини-приложение ↗",
            "lang":    "Изменить язык",
        },
        "en": {
            "deal":    "Create deal",
            "balance": "My balance",
            "details": "Requisites",
            "channel": "Channel ↗",
            "refs":    "Referrals",
            "tickets": "Tickets",
            "support": "Support ↗",
            "miniapp": "Mini App ↗",
            "lang":    "Change language",
        },
        "ar": {
            "deal":    "إنشاء صفقة",
            "balance": "رصيدي",
            "details": "التفاصيل",
            "channel": "القناة ↗",
            "refs":    "الإحالات",
            "tickets": "الطلبات",
            "support": "الدعم ↗",
            "miniapp": "التطبيق المصغر ↗",
            "lang":    "تغيير اللغة",
        },
        "zh": {
            "deal":    "创建交易",
            "balance": "我的余额",
            "details": "收款信息",
            "channel": "频道 ↗",
            "refs":    "推荐",
            "tickets": "申请",
            "support": "支持 ↗",
            "miniapp": "小程序 ↗",
            "lang":    "更改语言",
        },
    }
    t = labels.get(lang, labels["ru"])

    keyboard = [
        [InlineKeyboardButton(t["deal"],    callback_data="menu_deal",    style="primary", icon_custom_emoji_id=IC_CART)],
        [
            InlineKeyboardButton(t["balance"],  callback_data="menu_balance", style="primary", icon_custom_emoji_id=IC_BRIEF),
            InlineKeyboardButton(t["details"],  callback_data="menu_details", style="primary", icon_custom_emoji_id=IC_FOLDER),
        ],
        [
            InlineKeyboardButton(t["channel"],  url=URL_CHANNEL,              style="primary", icon_custom_emoji_id=IC_CHART),
            InlineKeyboardButton(t["refs"],     callback_data="menu_refs",    style="primary", icon_custom_emoji_id=IC_USERS),
        ],
        [
            InlineKeyboardButton(t["tickets"],  callback_data="menu_tickets", style="primary", icon_custom_emoji_id=IC_MAIL),
            InlineKeyboardButton(t["support"],  url=URL_SUPPORT,              style="primary", icon_custom_emoji_id=IC_DEV),
        ],
        [InlineKeyboardButton(t["miniapp"],  url=URL_MINI_APP,             style="primary", icon_custom_emoji_id=IC_SCREEN)],
        [InlineKeyboardButton(t["lang"],     callback_data="change_lang",  style="primary", icon_custom_emoji_id=IC_TEXT)],
    ]
    return InlineKeyboardMarkup(keyboard)


# ── Тексты приветствия по языкам ─────────────────────────────────────────────
WELCOME_TEXTS = {
    "ru": (
        f"Добро пожаловать {E_WAVE}\n\n"
        f"{E_BRIEF} Transfer - Мы специализированный сервис по обеспечению безопасности вне биржевых сделок.\n\n"
        f"{E_SPARK} Автоматизированый алгоритм исполнения.\n"
        f"{E_LIGHT} Скорость и автоматизация.\n"
        f"{E_CARD} Удобный и быстрый вывод средств.\n\n"
        "• Комиссия сервиса: 1%\n"
        "• Режим работы: 24/7\n"
        "• Техническая поддержка: @TransferMetaSup\n"
        "\n"
        f"{E_SHIELD} Выберите нужный раздел ниже:"
    ),
    "en": (
        f"Welcome {E_WAVE}\n\n"
        f"{E_BRIEF} Transfer - We are a specialized service for securing OTC deals.\n\n"
        f"{E_SPARK} Automated execution algorithm.\n"
        f"{E_LIGHT} Speed and automation.\n"
        f"{E_CARD} Convenient and fast withdrawal.\n\n"
        "• Service commission: 1%\n"
        "• Working hours: 24/7\n"
        "• Technical support: @TransferMetaSup\n"
        "\n"
        f"{E_SHIELD} Choose a section below:"
    ),
    "ar": (
        f"مرحباً {E_WAVE}\n\n"
        f"{E_BRIEF} Transfer - نحن خدمة متخصصة في تأمين الصفقات خارج البورصة.\n\n"
        f"{E_SPARK} خوارزمية تنفيذ آلية.\n"
        f"{E_LIGHT} السرعة والأتمتة.\n"
        f"{E_CARD} سحب مريح وسريع للأموال.\n\n"
        "• عمولة الخدمة: 1%\n"
        "• ساعات العمل: 24/7\n"
        "• الدعم الفني: @TransferMetaSup\n@"
        "\n"
        f"{E_SHIELD} اختر القسم المطلوب أدناه:"
    ),
    "zh": (
        f"欢迎 {E_WAVE}\n\n"
        f"{E_BRIEF} Transfer - 我们是专业的场外交易安全服务商。\n\n"
        f"{E_SPARK} 自动化执行算法。\n"
        f"{E_LIGHT} 速度与自动化。\n"
        f"{E_CARD} 便捷快速的资金提取。\n\n"
        "• 服务佣金：1%\n"
        "• 工作时间：24/7\n"
        "• 技术支持：@TransferMetaSup\n"
        "\n"
        f"{E_SHIELD} 请在下方选择所需版块："
    ),
}


# ── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    lang = context.user_data.get("language", "ru")
    user = update.effective_user
    log_msg = build_log(
        user=user,
        title="Команда /start",
        lines=[
            f"📎 Аргументы: {args if args else 'Нет'}",
        ],
    )
    logger.info(log_msg.replace("\n", " | "))

    # ── Переход по реферальной ссылке сделки ─────────────────────────────────
    if args and not args[0].startswith("ref_"):
        ref_code = args[0]
        deal = DEALS.get(ref_code)
        if deal:
            log_msg = build_log(
                user=user,
                title="Переход по ссылке сделки",
                lines=[
                    f"🔗 Сделка: <code>{ref_code}</code>",
                ],
            )
            logger.info(log_msg.replace("\n", " | "))
            user = update.effective_user
            user_name = f"@{user.username}" if user.username else f"#{user.id}"

            if deal["role"] == "seller":
                # Покупатель открыл ссылку сделки, созданной продавцом
                if user.id == deal["seller_id"]:
                    await update.message.reply_text("❌ Нельзя присоединиться к собственной сделке.")
                    return

                deal["buyer_id"] = user.id
                deal["buyer_name"] = user_name

                commission = round(deal["amount"] * 0.01, 2)
                net = round(deal["amount"] - commission, 2)

                # Уведомление продавцу
                join_notify = (
                    f'<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji> Пользователь {user_name}\n'
                    f"Присоединился к сделке <b>#{ref_code}</b>\n\n"
                    f'<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji> Успешных сделок покупателя: {context.user_data.get("deals_count", 0)}\n'
                    f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> Проверенный пользователь\n\n'
                    f"⚠️ Проверьте соответствие пользователя"
                )
                try:
                    await context.bot.send_message(deal["seller_id"], join_notify, parse_mode="HTML")
                except Exception:
                    pass

                # Сообщение покупателю
                buyer_text = (
                    f'<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji> <b>Информация о сделке #{ref_code}</b>\n\n'
                    f'<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji> Вы покупатель в сделке.\n'
                    f'<tg-emoji emoji-id="5204094761689963044">📩</tg-emoji> Продавец: {deal["seller_name"]}\n\n'
                    f'<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Вы покупаете: {deal["description"]}\n\n'
                    f'<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> Способ оплаты: {deal["currency"]}\n\n'
                    f"ID сделки: <code>{ref_code}</code>\n\n\n"
                    f"Сумма к оплате: {deal['amount']} {deal['currency']}\n\n"
                    f"⚠️ Пожалуйста, следуйте инструкциям продавца по оплате.\n"
                    f"Сохраните ID сделки для подтверждения!\n\n"
                    f"В случае проблем с оплатой обратитесь в поддержку — {URL_SUPPORT}"
                )
                buyer_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"confirm_pay_{ref_code}")],
                    [InlineKeyboardButton("❌ Выйти со сделки",   callback_data=f"exit_deal_{ref_code}")],
                ])
                if context.user_data.get("language"):
                    await update.message.reply_text(buyer_text, parse_mode="HTML", reply_markup=buyer_kb)
                else:
                    context.user_data["pending_deal"] = ref_code
                    keyboard = [
                        [InlineKeyboardButton("🇷🇺  Русский", callback_data="lang_ru", style="primary")],
                        [InlineKeyboardButton("🇬🇧  English", callback_data="lang_en", style="primary")],
                        [InlineKeyboardButton("🇸🇦  العربية", callback_data="lang_ar", style="primary")],
                        [InlineKeyboardButton("🇨🇳  中文",     callback_data="lang_zh", style="primary")],
                    ]
                    await update.message.reply_text(
                        "🌐 Выберите язык / Choose language / اختر اللغة:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                return
            else:
                # Продавец открыл ссылку сделки, созданной покупателем
                if user.id == deal["buyer_id"]:
                    await update.message.reply_text("❌ Нельзя присоединиться к собственной сделке.")
                    return

                deal["seller_id"] = user.id
                deal["seller_name"] = user_name

                commission = round(deal["amount"] * 0.01, 2)
                net = round(deal["amount"] - commission, 2)

                # Уведомление покупателю
                join_notify = (
                    f'<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji> Пользователь {user_name}\n'
                    f"Присоединился к сделке <b>#{ref_code}</b>\n\n"
                    f'<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji> Успешных сделок продавца: {context.user_data.get("deals_count", 0)}\n'
                    f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> Проверенный пользователь\n\n'
                    f"⚠️ Проверьте соответствие пользователя"
                )
                try:
                    await context.bot.send_message(deal["buyer_id"], join_notify, parse_mode="HTML")
                except Exception:
                    pass

                # Сообщение продавцу
                seller_text = (
                    f'<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji> <b>Информация о сделке #{ref_code}</b>\n\n'
                    f'<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji> Вы продавец в сделке.\n'
                    f'<tg-emoji emoji-id="5204094761689963044">📩</tg-emoji> Покупатель: {deal["buyer_name"]}\n\n'
                    f'<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Вы продаёте: {deal["description"]}\n\n'
                    f'<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> Способ оплаты: {deal["currency"]}\n\n'
                    f"ID сделки: <code>{ref_code}</code>\n\n\n"
                    f"Сумма к получению: {net} {deal['currency']}\n\n"
                    f"⚠️ Ожидайте подтверждения оплаты от покупателя.\n"
                    f"Сохраните ID сделки!\n\n"
                    f"В случае проблем обратитесь в поддержку — {URL_SUPPORT}"
                )
                seller_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Выйти со сделки",   callback_data=f"exit_deal_{ref_code}")],
                ])
                if context.user_data.get("language"):
                    await update.message.reply_text(seller_text, parse_mode="HTML", reply_markup=seller_kb)
                else:
                    context.user_data["pending_deal"] = ref_code
                    keyboard = [
                        [InlineKeyboardButton("🇷🇺  Русский", callback_data="lang_ru", style="primary")],
                        [InlineKeyboardButton("🇬🇧  English", callback_data="lang_en", style="primary")],
                        [InlineKeyboardButton("🇸🇦  العربية", callback_data="lang_ar", style="primary")],
                        [InlineKeyboardButton("🇨🇳  中文",     callback_data="lang_zh", style="primary")],
                    ]
                    await update.message.reply_text(
                        "🌐 Выберите язык / Choose language / اختر اللغة:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                return

    # ── Если язык уже выбран — сразу показываем меню ─────────────────────────
    if context.user_data.get("language"):
        await send_welcome(update, context, lang)
        return

    keyboard = [
        [InlineKeyboardButton("🇷🇺  Русский", callback_data="lang_ru", style="primary")],
        [InlineKeyboardButton("🇬🇧  English", callback_data="lang_en", style="primary")],
        [InlineKeyboardButton("🇸🇦  العربية", callback_data="lang_ar", style="primary")],
        [InlineKeyboardButton("🇨🇳  中文",     callback_data="lang_zh", style="primary")],
    ]
    await update.message.reply_text(
        "🌐 Выберите язык / Choose language / اختر اللغة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Отправка приветственного экрана с меню ───────────────────────────────────
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    text = WELCOME_TEXTS.get(lang, WELCOME_TEXTS["ru"])
    chat_id = update.effective_chat.id
    reply_markup = main_menu_keyboard(lang)
    # Попробуем сначала языковой вариант, потом русский, потом дефолтный
    logo_path = LOGO_PATH.get(lang, LOGO_PATH.get("ru", LOGO_PATH["default"]))

    try:
        with open(logo_path, "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
    except FileNotFoundError:
        # Если не нашли русский, попробуем дефолтный
        try:
            with open(LOGO_PATH["default"], "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
        except FileNotFoundError:
            # Если и дефолтный отсутствует, отправляем просто текст
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )


# ── Обработка нажатий кнопок выбора языка ────────────────────────────────────
async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    lang = query.data.replace("lang_", "")
    context.user_data["language"] = lang

    await query.edit_message_reply_markup(reply_markup=None)
    await send_welcome(update, context, lang)


# ── Смена языка из главного меню ─────────────────────────────────────────────
async def change_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🇷🇺  Русский", callback_data="lang_ru", style="primary")],
        [InlineKeyboardButton("🇬🇧  English", callback_data="lang_en", style="primary")],
        [InlineKeyboardButton("🇸🇦  العربية", callback_data="lang_ar", style="primary")],
        [InlineKeyboardButton("🇨🇳  中文",     callback_data="lang_zh", style="primary")],
    ]
    await query.message.reply_text(
        "🌐 Выберите язык / Choose language / اختر اللغة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Экран выбора роли в сделке ───────────────────────────────────────────────
DEAL_ROLE_TEXTS = {
    "ru": f'<tg-emoji emoji-id="5276262671962892944">🛡</tg-emoji> Выберите вашу роль в сделке:',
    "en": f'<tg-emoji emoji-id="5276262671962892944">🛡</tg-emoji> Choose your role in the deal:',
    "ar": f'<tg-emoji emoji-id="5276262671962892944">🛡</tg-emoji> اختر دورك في الصفقة:',
    "zh": f'<tg-emoji emoji-id="5276262671962892944">🛡</tg-emoji> 请选择您在交易中的角色：',
}

DEAL_ROLE_LABELS = {
    "ru": {"seller": "💼 Я Продавец", "buyer": "🛒 Я Покупатель", "back": "Вернуться в меню"},
    "en": {"seller": "💼 I'm Seller",  "buyer": "🛒 I'm Buyer",    "back": "Back to menu"},
    "ar": {"seller": "💼 أنا البائع",  "buyer": "🛒 أنا المشتري",  "back": "العودة إلى القائمة"},
    "zh": {"seller": "💼 我是卖家",     "buyer": "🛒 我是买家",      "back": "返回菜单"},
}

IC_SELLER = "5276037216244624892"   # портфель — Продавец
IC_BUYER  = "5278613311858959074"   # корзина  — Покупатель

E_SHIELD2 = '<tg-emoji emoji-id="5276262671962892944">🛡</tg-emoji>'


def deal_role_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = DEAL_ROLE_LABELS.get(lang, DEAL_ROLE_LABELS["ru"])
    keyboard = [
        [InlineKeyboardButton(t["seller"], callback_data="role_seller", style="primary")],
        [InlineKeyboardButton(t["buyer"],  callback_data="role_buyer",  style="primary")],
        [InlineKeyboardButton(t["back"],   callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ── Кнопка "Создать сделку" ───────────────────────────────────────────────────
async def menu_deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    text = DEAL_ROLE_TEXTS.get(lang, DEAL_ROLE_TEXTS["ru"])
    await _send_photo_or_text(query, text, parse_mode="HTML", reply_markup=deal_role_keyboard(lang), photo_path=IMG_DEAL, lang=lang)


# ── Экран выбора метода оплаты (Продавец) ────────────────────────────────────
PAYMENT_METHOD_TEXTS = {
    "ru": "Выберите метод получения оплаты:",
    "en": "Choose payment method:",
    "ar": "اختر طريقة الدفع:",
    "zh": "请选择收款方式：",
}

PAYMENT_METHOD_LABELS = {
    "ru": {
        "ton":  "На TON-кошелек",
        "card": "Перевод на карту / СБП",
        "stars": "Звезды",
        "back": "Вернуться в меню",
    },
    "en": {
        "ton":  "To TON wallet",
        "card": "Card / Bank transfer",
        "stars": "Stars",
        "back": "Back to menu",
    },
    "ar": {
        "ton":  "إلى محفظة TON",
        "card": "تحويل بنكي / بطاقة",
        "stars": "النجوم",
        "back": "العودة إلى القائمة",
    },
    "zh": {
        "ton":  "TON钱包",
        "card": "银行卡转账",
        "stars": "星星",
        "back": "返回菜单",
    },
}

IC_SPARK2 = "5890925363067886150"   # ✨ искры
IC_STAR   = "5402104393396931859"   # ⭐️ звезда
IC_HEART  = "5330131801056768633"   # 💛 сердце — Вернуться в меню


def payment_method_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = PAYMENT_METHOD_LABELS.get(lang, PAYMENT_METHOD_LABELS["ru"])
    keyboard = [
        [InlineKeyboardButton(t["ton"],   callback_data="pay_ton",   style="primary", icon_custom_emoji_id=IC_SPARK2)],
        [InlineKeyboardButton(t["card"],  callback_data="pay_card",  style="primary", icon_custom_emoji_id=IC_SPARK2)],
        [InlineKeyboardButton(t["stars"], callback_data="pay_stars", style="primary", icon_custom_emoji_id=IC_STAR)],
        [InlineKeyboardButton(t["back"],  callback_data="back_to_menu", style="primary", icon_custom_emoji_id=IC_HEART)],
    ]
    return InlineKeyboardMarkup(keyboard)


# ── Обработчик роли "Продавец" ────────────────────────────────────────────────
async def role_seller_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    context.user_data["deal_role"] = "seller"
    text = PAYMENT_METHOD_TEXTS.get(lang, PAYMENT_METHOD_TEXTS["ru"])
    await query.message.reply_text(text, reply_markup=payment_method_keyboard(lang))


# ── Обработчик роли "Покупатель" ───────────────────────────────────────────────
async def role_buyer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    context.user_data["deal_role"] = "buyer"
    text = PAYMENT_METHOD_TEXTS.get(lang, PAYMENT_METHOD_TEXTS["ru"])
    await query.message.reply_text(text, reply_markup=payment_method_keyboard(lang))


# ── Клавиатура с одной кнопкой "Вернуться в меню" ────────────────────────────
BACK_LABEL = {
    "ru": "Вернуться в меню",
    "en": "Back to menu",
    "ar": "العودة إلى القائمة",
    "zh": "返回菜单",
}

def back_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            BACK_LABEL.get(lang, BACK_LABEL["ru"]),
            callback_data="back_to_menu",
            style="primary",
            icon_custom_emoji_id=IC_HEART,
        )
    ]])


# ── Генератор рандомного реферального кода ────────────────────────────────────
def make_ref_code(length: int = 10) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


# ── Тексты для шагов сделки ───────────────────────────────────────────────────
IC_BRIEF_DEAL = "5893255507380014983"   # портфель для заголовка сделки

DEAL_HEADER = {
        "ru": f'<tg-emoji emoji-id="{IC_BRIEF_DEAL}">💼</tg-emoji> Создание сделки\n\n',
    "en": f'<tg-emoji emoji-id="{IC_BRIEF_DEAL}">💼</tg-emoji> Deal creation\n\n',
    "ar": f'<tg-emoji emoji-id="{IC_BRIEF_DEAL}">💼</tg-emoji> إنشاء الصفقة\n\n',
    "zh": f'<tg-emoji emoji-id="{IC_BRIEF_DEAL}">💼</tg-emoji> 创建交易\n\n',
}

ENTER_AMOUNT = {
    "ton":   {"ru": "Введите сумму (TON) в формате: 100.5",   "en": "Enter amount (TON), e.g.: 100.5",   "ar": "أدخل المبلغ (TON) مثال: 100.5",   "zh": "请输入金额 (TON)，格式：100.5"},
    "card":  {"ru": "Введите сумму (RUB) в формате: 1000.50", "en": "Enter amount (RUB), e.g.: 1000.50", "ar": "أدخل المبلغ (RUB) مثال: 1000.50", "zh": "请输入金额 (RUB)，格式：1000.50"},
    "stars": {"ru": "Введите сумму (Звезд) в формате: 100.5", "en": "Enter amount (Stars), e.g.: 100.5", "ar": "أدخل المبلغ (نجوم) مثال: 100.5",  "zh": "请输入金额（星星），格式：100.5"},
}

CARD_REQUISITES_MISSING = {
    "ru": '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> Реквизиты не добавлены.\n\nДобавьте карту/телефон в разделе <b>Реквизиты</b>.',
    "en": '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> Requisites not added.\n\nAdd card/phone in <b>Requisites</b>.',
    "ar": '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> لم تتم إضافة التفاصيل.\n\nأضف البطاقة/الهاتف في <b>التفاصيل</b>.',
    "zh": '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> 未添加收款信息。\n\n请在 <b>收款信息</b> 中添加银行卡/手机号。',
}

ENTER_DESCRIPTION = {
    "ru": "Укажите, что вы предлагаете в этой сделке. Пример: 10 Кепок и Пепе...",
    "en": "Describe what you offer in this deal. Example: 10 Caps and Pepe...",
    "ar": "صف ما تقدمه في هذه الصفقة. مثال: 10 Caps and Pepe...",
    "zh": "描述您在此交易中提供的内容。例如：10 Caps and Pepe...",
}

DEAL_CREATED_TEXTS = {
    "ru": (
        '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> Сделка успешно создана!\n\n'
        "Сумма: {amount} {currency}\n"
        '<tg-emoji emoji-id="5890925363067886150">✨</tg-emoji> Валюта: {currency}\n'
        '<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Описание: {description}\n'
        "Ссылка для {counterparty}:\n"
        "https://t.me/{bot}?start={ref}\n\n"
        "Скопируйте ссылку и отправьте {counterparty_dative}."
    ),
    "en": (
        '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> Deal created successfully!\n\n'
        "Amount: {amount} {currency}\n"
        '<tg-emoji emoji-id="5890925363067886150">✨</tg-emoji> Currency: {currency}\n'
        '<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Description: {description}\n'
        "Link for {counterparty}:\n"
        "https://t.me/{bot}?start={ref}\n\n"
        "Copy the link and send it to the {counterparty}."
    ),
    "ar": (
        '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> تم إنشاء الصفقة بنجاح!\n\n'
        "المبلغ: {amount} {currency}\n"
        '<tg-emoji emoji-id="5890925363067886150">✨</tg-emoji> العملة: {currency}\n'
        '<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> الوصف: {description}\n'
        "رابط {counterparty}:\n"
        "https://t.me/{bot}?start={ref}\n\n"
        "انسخ الرابط وأرسله لـ{counterparty}."
    ),
    "zh": (
        '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> 交易创建成功！\n\n'
        "金额：{amount} {currency}\n"
        '<tg-emoji emoji-id="5890925363067886150">✨</tg-emoji> 货币：{currency}\n'
        '<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> 描述：{description}\n'
        "{counterparty}链接：\n"
        "https://t.me/{bot}?start={ref}\n\n"
        "复制链接并发送给{counterparty}。"
    ),
}

COUNTERPARTY = {
    "seller": {
        "ru":  ("покупателя", "покупателю"),
        "en":  ("buyer",      "buyer"),
        "ar":  ("المشتري",    "المشتري"),
        "zh":  ("买家",        "买家"),
    },
    "buyer": {
        "ru":  ("продавца",   "продавцу"),
        "en":  ("seller",     "seller"),
        "ar":  ("البائع",     "البائع"),
        "zh":  ("卖家",        "卖家"),
    },
}

CURRENCY_LABEL = {"ton": "TON", "stars": "Stars", "card": "RUB"}


# ── Обработчик методов оплаты ─────────────────────────────────────────────────
async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    method = query.data.replace("pay_", "")  # "ton" / "card" / "stars"
    context.user_data["pay_method"] = method

    header = DEAL_HEADER.get(lang, DEAL_HEADER["ru"])
    body = ENTER_AMOUNT.get(method, {}).get(lang, "...")

    if method == "card":
        if not context.user_data.get("details_card"):
            await query.message.reply_text(
                CARD_REQUISITES_MISSING.get(lang, CARD_REQUISITES_MISSING["ru"]),
                parse_mode="HTML",
                reply_markup=back_keyboard(lang),
            )
        else:
            await query.message.reply_text(
                f"{header}{body}",
                parse_mode="HTML",
                reply_markup=back_keyboard(lang),
            )
            context.user_data["awaiting_amount"] = True
    else:
        await query.message.reply_text(
            f"{header}{body}",
            parse_mode="HTML",
            reply_markup=back_keyboard(lang),
        )
        # Ждём ввода суммы от пользователя
        context.user_data["awaiting_amount"] = True


# ── Вернуться в меню ──────────────────────────────────────────────────────────
async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    await send_welcome(update, context, lang)


# ── Заглушки для остальных кнопок меню ───────────────────────────────────────
async def menu_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    user = query.from_user
    username = f"@{user.username}" if user.username else f"#{user.id}"

    E_HAND   = '<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji>'
    E_DOLLAR = '<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji>'
    E_CARD2  = '<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji>'
    E_FOLDER2= '<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji>'
    E_TON    = '<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji>'
    E_XMARK  = '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji>'
    E_CASE   = '<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji>'

    texts = {
        "ru": (
            f"<b>ВАШ БАЛАНС</b>\n\n"
            f"{E_HAND} Пользователь: {username}\n\n"
            f"<b>Доступные средства:</b>\n"
            f"{E_DOLLAR} {BALANCES.get(user.id, {}).get('RUB', 0.0):.2f} RUB\n{E_TON} {BALANCES.get(user.id, {}).get('TON', 0.0):.2f} TON\n⭐️ {BALANCES.get(user.id, {}).get('Stars', 0.0):.2f} Stars\n\n"
            f"{E_CARD2} Информация о выводе средств:\n"
            f"{E_TON} TON-кошелек: {E_XMARK} TON-кошелек не добавлен\n"
            f"{E_CARD2} Карта / СБП: {E_XMARK} Реквизиты не добавлены\n\n"
            f"{E_FOLDER2} Информация:\n"
            f"• Комиссия системы: 1%\n"
            f"• Вывод доступен на карту, номер или TON-кошелек\n\n"
            f"{E_CASE} Успешных сделок: {context.user_data.get('deals_count', 0)}"
        ),
        "en": (
            f"<b>YOUR BALANCE</b>\n\n"
            f"{E_HAND} User: {username}\n\n"
            f"<b>Available funds:</b>\n"
            f"{E_DOLLAR} {BALANCES.get(user.id, {}).get('RUB', 0.0):.2f} RUB\n{E_TON} {BALANCES.get(user.id, {}).get('TON', 0.0):.2f} TON\n⭐️ {BALANCES.get(user.id, {}).get('Stars', 0.0):.2f} Stars\n\n"
            f"{E_CARD2} Withdrawal info:\n"
            f"{E_TON} TON wallet: {E_XMARK} TON wallet not added\n"
            f"{E_CARD2} Card / SBP: {E_XMARK} Requisites not added\n\n"
            f"{E_FOLDER2} Info:\n"
            f"• System commission: 1%\n"
            f"• Withdrawal available to card, number or TON wallet\n\n"
            f"{E_CASE} Successful deals: {context.user_data.get('deals_count', 0)}"
        ),
        "ar": (
            f"<b>رصيدك</b>\n\n"
            f"{E_HAND} المستخدم: {username}\n\n"
            f"<b>الأموال المتاحة:</b>\n"
            f"{E_DOLLAR} {BALANCES.get(user.id, {}).get('RUB', 0.0):.2f} RUB\n{E_TON} {BALANCES.get(user.id, {}).get('TON', 0.0):.2f} TON\n⭐️ {BALANCES.get(user.id, {}).get('Stars', 0.0):.2f} Stars\n\n"
            f"{E_CARD2} معلومات السحب:\n"
            f"{E_TON} محفظة TON: {E_XMARK} لم تتم إضافة المحفظة\n"
            f"{E_CARD2} البطاقة / SBP: {E_XMARK} لم تتم إضافة التفاصيل\n\n"
            f"{E_FOLDER2} معلومات:\n"
            f"• عمولة النظام: 1%\n"
            f"• السحب متاح على البطاقة أو الرقم أو محفظة TON\n\n"
            f"{E_CASE} الصفقات الناجحة: {context.user_data.get('deals_count', 0)}"
        ),
        "zh": (
            f"<b>您的余额</b>\n\n"
            f"{E_HAND} 用户: {username}\n\n"
            f"<b>可用资金:</b>\n"
            f"{E_DOLLAR} {BALANCES.get(user.id, {}).get('RUB', 0.0):.2f} RUB\n{E_TON} {BALANCES.get(user.id, {}).get('TON', 0.0):.2f} TON\n⭐️ {BALANCES.get(user.id, {}).get('Stars', 0.0):.2f} Stars\n\n"
            f"{E_CARD2} 提款信息:\n"
            f"{E_TON} TON钱包: {E_XMARK} 未添加TON钱包\n"
            f"{E_CARD2} 银行卡 / SBP: {E_XMARK} 未添加收款信息\n\n"
            f"{E_FOLDER2} 信息:\n"
            f"• 系统佣金: 1%\n"
            f"• 可提款至银行卡、号码或TON钱包\n\n"
            f"{E_CASE} 成功交易: {context.user_data.get('deals_count', 0)}"
        ),
    }

    text = texts.get(lang, texts["ru"])

    balance_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            {"ru": "Вывести средства", "en": "Withdraw funds", "ar": "سحب الأموال", "zh": "提款"}.get(lang, "Вывести средства"),
            callback_data="balance_withdraw",
            style="primary",
            icon_custom_emoji_id="5208485880418820053",
        )],
        [InlineKeyboardButton(
            {"ru": "История операций", "en": "Transaction history", "ar": "سجل العمليات", "zh": "交易历史"}.get(lang, "История операций"),
            callback_data="balance_history",
            style="primary",
            icon_custom_emoji_id="5204094761689963044",
        )],
        [InlineKeyboardButton(
            BACK_LABEL.get(lang, BACK_LABEL["ru"]),
            callback_data="back_to_menu",
            style="primary",
            icon_custom_emoji_id=IC_HEART,
        )],
    ])
    await _send_photo_or_text(query, text, parse_mode="HTML", reply_markup=balance_keyboard, photo_path=IMG_BALANCE, lang=lang)


# ── Вывод средств ─────────────────────────────────────────────────────────────
E_DOLLAR_W = '<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji>'

async def balance_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    user = query.from_user
    bal = BALANCES.get(user.id, {})
    rub = bal.get("RUB", 0.0)
    ton = bal.get("TON", 0.0)
    stars = bal.get("Stars", 0.0)

    texts = {
        "ru": (
            f"<b>ВЫВОД СРЕДСТВ</b>\n\n"
            f"<b>Ваши балансы:</b>\n"
            f"{E_DOLLAR_W} {rub:.2f} RUB\n<tg-emoji emoji-id=\"5388774339623540025\">🪙</tg-emoji> {ton:.2f} TON\n⭐️ {stars:.2f} Stars\n\n"
            f"Выберите способ вывода:"
        ),
        "en": (
            f"<b>WITHDRAWAL</b>\n\n"
            f"<b>Your balances:</b>\n"
            f"{E_DOLLAR_W} {rub:.2f} RUB\n<tg-emoji emoji-id=\"5388774339623540025\">🪙</tg-emoji> {ton:.2f} TON\n⭐️ {stars:.2f} Stars\n\n"
            f"Choose withdrawal method:"
        ),
        "ar": (
            f"<b>سحب الأموال</b>\n\n"
            f"<b>أرصدتك:</b>\n"
            f"{E_DOLLAR_W} {rub:.2f} RUB\n<tg-emoji emoji-id=\"5388774339623540025\">🪙</tg-emoji> {ton:.2f} TON\n⭐️ {stars:.2f} Stars\n\n"
            f"اختر طريقة السحب:"
        ),
        "zh": (
            f"<b>提款</b>\n\n"
            f"<b>您的余额：</b>\n"
            f"{E_DOLLAR_W} {rub:.2f} RUB\n<tg-emoji emoji-id=\"5388774339623540025\">🪙</tg-emoji> {ton:.2f} TON\n⭐️ {stars:.2f} Stars\n\n"
            f"请选择提款方式："
        ),
    }

    withdraw_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            {"ru": "На карту / по номеру", "en": "To card / by number", "ar": "بطاقة / رقم", "zh": "银行卡/号码"}.get(lang, "На карту / по номеру"),
            callback_data="withdraw_card",
            style="primary",
            icon_custom_emoji_id="5902056028513505203",
        )],
        [InlineKeyboardButton(
            {"ru": "🎰 На TON-кошелек", "en": "🎰 To TON wallet", "ar": "🎰 محفظة TON", "zh": "🎰 TON钱包"}.get(lang, "🎰 На TON-кошелек"),
            callback_data="withdraw_ton",
            style="primary",
        )],
        [InlineKeyboardButton(
            {"ru": "На Stars", "en": "To Stars", "ar": "نجوم", "zh": "Stars"}.get(lang, "На Stars"),
            callback_data="withdraw_stars",
            style="primary",
            icon_custom_emoji_id=IC_STAR,
        )],
        [InlineKeyboardButton(
            BACK_LABEL.get(lang, BACK_LABEL["ru"]),
            callback_data="back_to_menu",
            style="primary",
            icon_custom_emoji_id=IC_HEART,
        )],
    ])
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=withdraw_keyboard)


async def withdraw_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    user = query.from_user
    bal = BALANCES.get(user.id, {})
    rub = bal.get("RUB", 0.0)
    ton = bal.get("TON", 0.0)
    stars = bal.get("Stars", 0.0)

    text = (
        f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> '
        + {
            "ru": "<b>ЗАЯВКА НА ВЫВОД ПРИНЯТА!</b>",
            "en": "<b>WITHDRAWAL REQUEST ACCEPTED!</b>",
            "ar": "<b>تم استلام طلب السحب!</b>",
            "zh": "<b>提款申请已接受！</b>",
        }.get(lang, "<b>ЗАЯВКА НА ВЫВОД ПРИНЯТА!</b>")
        + f"\n\n"
        f"{ {'ru': '<b>Ваши балансы:</b>', 'en': '<b>Your balances:</b>', 'ar': '<b>أرصدتك:</b>', 'zh': '<b>您的余额：</b>'}.get(lang, '<b>Ваши балансы:</b>') }\n"
        f"{E_DOLLAR_W} {rub:.2f} RUB\n"
        f'<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji> {ton:.2f} TON\n'
        f"⭐️ {stars:.2f} Stars\n\n"
        f"{ {'ru': 'Вывод обрабатывается вручную. Ожидайте подтверждения менеджера.', 'en': 'Withdrawal is processed manually. Wait for manager confirmation.', 'ar': 'يتم معالجة السحب يدويًا. انتظر تأكيد المدير.', 'zh': '提款由人工处理，请等待管理员确认。'}.get(lang, 'Вывод обрабатывается вручную. Ожидайте подтверждения менеджера.') }"
    )
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=back_keyboard(lang))


async def balance_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    texts = {
        "ru": "📋 История операций пуста.",
        "en": "📋 Transaction history is empty.",
        "ar": "📋 سجل العمليات فارغ.",
        "zh": "📋 交易历史为空。",
    }
    await query.message.reply_text(texts.get(lang, texts["ru"]), reply_markup=back_keyboard(lang))


# ── Обращения ─────────────────────────────────────────────────────────────────
async def menu_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    texts = {
        "ru": (
            "<b>Transfer</b>\n<i>Центр обращений</i>\n\n"
            "Площадка для предложений и жалоб. Каждое обращение проверяется вручную.\n\n"
            "———\n\n"
            "<b>Предложения</b>\n"
            "→ Функционал и новые фичи\n"
            "→ Интеграции с биржами\n"
            "→ Отзывы о работе сервиса\n\n"
            "<b>Жалобы</b>\n"
            "→ Спорные транзакции\n"
            "→ Технические сбои\n"
            "→ Нарушения правил\n"
            "→ Подозрение на скам\n\n"
            "———\n\n"
            "<b>Регламент</b>\n\n"
            "→ Ответ в течение 24 часов\n"
            "→ Полная конфиденциальность\n"
            "→ Скам — мгновенная реакция\n"
            "→ Лучшие идеи внедряются\n\n"
            "Выберите тип обращения:"
        ),
        "en": (
            "<b>Transfer</b>\n<i>Support Center</i>\n\n"
            "Platform for suggestions and complaints. Each request is reviewed manually.\n\n"
            "———\n\n"
            "<b>Suggestions</b>\n"
            "→ Features and new ideas\n"
            "→ Exchange integrations\n"
            "→ Service feedback\n\n"
            "<b>Complaints</b>\n"
            "→ Disputed transactions\n"
            "→ Technical issues\n"
            "→ Rule violations\n"
            "→ Suspected scam\n\n"
            "———\n\n"
            "<b>Policy</b>\n\n"
            "→ Response within 24 hours\n"
            "→ Full confidentiality\n"
            "→ Scam — instant reaction\n"
            "→ Best ideas implemented\n\n"
            "Choose request type:"
        ),
        "ar": (
            "<b>Transfer</b>\n<i>مركز الدعم</i>\n\n"
            "منصة للاقتراحات والشكاوى. كل طلب يُراجع يدوياً.\n\n"
            "———\n\n"
            "<b>الاقتراحات</b>\n"
            "→ الميزات والأفكار الجديدة\n"
            "→ تكاملات البورصة\n"
            "→ ملاحظات الخدمة\n\n"
            "<b>الشكاوى</b>\n"
            "→ المعاملات المتنازع عليها\n"
            "→ المشاكل التقنية\n"
            "→ انتهاكات القواعد\n"
            "→ الاشتباه بالاحتيال\n\n"
            "———\n\n"
            "<b>السياسة</b>\n\n"
            "→ رد خلال 24 ساعة\n"
            "→ سرية تامة\n"
            "→ الاحتيال — رد فوري\n"
            "→ أفضل الأفكار تُنفَّذ\n\n"
            "اختر نوع الطلب:"
        ),
        "zh": (
            "<b>Transfer</b>\n<i>支持中心</i>\n\n"
            "建议和投诉平台，每个请求均手动审核。\n\n"
            "———\n\n"
            "<b>建议</b>\n"
            "→ 功能和新想法\n"
            "→ 交易所集成\n"
            "→ 服务反馈\n\n"
            "<b>投诉</b>\n"
            "→ 争议交易\n"
            "→ 技术问题\n"
            "→ 违规行为\n"
            "→ 疑似诈骗\n\n"
            "———\n\n"
            "<b>规则</b>\n\n"
            "→ 24小时内回复\n"
            "→ 完全保密\n"
            "→ 诈骗 — 即时响应\n"
            "→ 最佳想法将被实施\n\n"
            "选择请求类型："
        ),
    }

    tickets_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            {"ru": "💡 Предложить", "en": "💡 Suggest", "ar": "💡 اقتراح", "zh": "💡 建议"}.get(lang, "💡 Предложить"),
            callback_data="ticket_suggest",
        )],
        [InlineKeyboardButton(
            {"ru": "⚠️ Пожаловаться", "en": "⚠️ Complain", "ar": "⚠️ شكوى", "zh": "⚠️ 投诉"}.get(lang, "⚠️ Пожаловаться"),
            callback_data="ticket_complain",
        )],
        [InlineKeyboardButton(
            {"ru": "← Назад", "en": "← Back", "ar": "← رجوع", "zh": "← 返回"}.get(lang, "← Назад"),
            callback_data="back_to_menu",
        )],
    ])
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=tickets_keyboard)


async def ticket_suggest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    context.user_data["awaiting_ticket"] = "suggest"

    texts = {
        "ru": "💡 <b>Предложение</b>\n\nОпишите вашу идею или предложение в одном сообщении.\nОтправьте /cancel чтобы отменить.",
        "en": "💡 <b>Suggestion</b>\n\nDescribe your idea or suggestion in one message.\nSend /cancel to cancel.",
        "ar": "💡 <b>اقتراح</b>\n\nاصف فكرتك في رسالة واحدة.\nأرسل /cancel للإلغاء.",
        "zh": "💡 <b>建议</b>\n\n请在一条消息中描述您的想法。\n发送 /cancel 取消。",
    }
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        {"ru": "← Назад", "en": "← Back", "ar": "← رجوع", "zh": "← 返回"}.get(lang, "← Назад"),
        callback_data="menu_tickets",
    )]])
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=back_kb)


async def ticket_complain_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    context.user_data["awaiting_ticket"] = "complain"

    texts = {
        "ru": "⚠️ <b>Жалоба</b>\n\nОпишите проблему в одном сообщении. Если речь о пользователе — укажите его @username/ID. Отправьте /cancel чтобы отменить.",
        "en": "⚠️ <b>Complaint</b>\n\nDescribe the problem in one message. If it's about a user — provide their @username/ID. Send /cancel to cancel.",
        "ar": "⚠️ <b>شكوى</b>\n\nاصف المشكلة في رسالة واحدة. إذا كانت عن مستخدم — أدخل @username/ID. أرسل /cancel للإلغاء.",
        "zh": "⚠️ <b>投诉</b>\n\n请在一条消息中描述问题。如果涉及用户，请提供 @username/ID。发送 /cancel 取消。",
    }
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        {"ru": "← Назад", "en": "← Back", "ar": "← رجوع", "zh": "← 返回"}.get(lang, "← Назад"),
        callback_data="menu_tickets",
    )]])
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=back_kb)


# ── Рефералы ──────────────────────────────────────────────────────────────────
async def menu_refs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    # Генерируем реф-код один раз и сохраняем за пользователем
    if "ref_code" not in context.user_data:
        context.user_data["ref_code"] = "ref_" + make_ref_code(8)
    ref_code = context.user_data["ref_code"]
    ref_link = f"https://t.me/{BOT_USERNAME}?start={ref_code}"

    texts = {
        "ru": (
            f"<b>Transfer</b>\n<i>Affiliate Program</i>\n\n"
            f"→ Рефералов · 0\n\n"
            f"<b>Ваша ссылка</b>\n"
            f"{ref_link}\n\n"
            f"———\n\n"
            f"<b>Как это работает</b>\n\n"
            f"→ Бонус за каждого нового пользователя\n"
            f"→ Доход растёт пропорционально\n"
            f"→ Начисления со всех операций\n\n"
            f"<i>Поделитесь ссылкой и растите вместе с платформой</i>"
        ),
        "en": (
            f"<b>Transfer</b>\n<i>Affiliate Program</i>\n\n"
            f"→ Referrals · 0\n\n"
            f"<b>Your link</b>\n"
            f"{ref_link}\n\n"
            f"———\n\n"
            f"<b>How it works</b>\n\n"
            f"→ Bonus for each new user\n"
            f"→ Income grows proportionally\n"
            f"→ Accruals from all operations\n\n"
            f"<i>Share the link and grow with the platform</i>"
        ),
        "ar": (
            f"<b>Transfer</b>\n<i>Affiliate Program</i>\n\n"
            f"→ الإحالات · 0\n\n"
            f"<b>رابطك</b>\n"
            f"{ref_link}\n\n"
            f"———\n\n"
            f"<b>كيف يعمل</b>\n\n"
            f"→ مكافأة لكل مستخدم جديد\n"
            f"→ الدخل ينمو بشكل متناسب\n"
            f"→ استحقاقات من جميع العمليات\n\n"
            f"<i>شارك الرابط وانمُ مع المنصة</i>"
        ),
        "zh": (
            f"<b>Transfer</b>\n<i>Affiliate Program</i>\n\n"
            f"→ 推荐人数 · 0\n\n"
            f"<b>您的链接</b>\n"
            f"{ref_link}\n\n"
            f"———\n\n"
            f"<b>如何运作</b>\n\n"
            f"→ 每位新用户奖励\n"
            f"→ 收入按比例增长\n"
            f"→ 所有操作均有收益\n\n"
            f"<i>分享链接，与平台共同成长</i>"
        ),
    }

    refs_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            {"ru": "🔗 Поделиться ссылкой", "en": "🔗 Share link", "ar": "🔗 مشاركة الرابط", "zh": "🔗 分享链接"}.get(lang, "🔗 Поделиться ссылкой"),
            switch_inline_query=ref_link,
        )],
        [InlineKeyboardButton(
            {"ru": "← Назад", "en": "← Back", "ar": "← رجوع", "zh": "← 返回"}.get(lang, "← Назад"),
            callback_data="back_to_menu",
        )],
    ])
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=refs_keyboard, disable_web_page_preview=True)


async def menu_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    E_ENVELOPE = '<tg-emoji emoji-id="5204094761689963044">📩</tg-emoji>'
    E_TG       = '<tg-emoji emoji-id="6028346797368283073">✈️</tg-emoji>'
    E_TON2     = '<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji>'
    E_CARD3    = '<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji>'
    E_CHECK    = '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji>'
    E_XMARK    = '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji>'

    # Получаем сохраненные реквизиты
    saved_ton = context.user_data.get("details_ton")
    saved_card = context.user_data.get("details_card")
    saved_region = context.user_data.get("details_region")

    # Формируем текст с реквизитами
    ton_text = ""
    if saved_ton:
        ton_text = f"{E_TON2} TON-кошелек: {E_CHECK} <code>{saved_ton}</code>\n"
    else:
        ton_text = f"{E_TON2} TON-кошелек: {E_XMARK} Не добавлен\n"

    card_text = ""
    if saved_card:
        region_display = f" ({saved_region})" if saved_region else ""
        card_text = f"{E_CARD3} Карта/телефон{region_display}: {E_CHECK} <code>{saved_card}</code>\n"
    else:
        card_text = f"{E_CARD3} Карта/телефон: {E_XMARK} Не добавлен\n"

    texts = {
        "ru": f"{E_ENVELOPE} Управление реквизитами\n\n{ton_text}{card_text}\nИспользуйте кнопки ниже чтобы добавить/изменить реквизиты {E_TG}",
        "en": f"{E_ENVELOPE} Requisites management\n\n{ton_text}{card_text}\nUse the buttons below to add/change requisites {E_TG}",
        "ar": f"{E_ENVELOPE} إدارة التفاصيل\n\n{ton_text}{card_text}\nاستخدم الأزرار أدناه لإضافة/تغيير التفاصيل {E_TG}",
        "zh": f"{E_ENVELOPE} 收款信息管理\n\n{ton_text}{card_text}\n使用下方按钮添加/修改收款信息 {E_TG}",
    }

    details_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            {"ru": "Добавить/изменить TON-Кошелек", "en": "Add/change TON Wallet", "ar": "إضافة/تغيير محفظة TON", "zh": "添加/修改TON钱包"}.get(lang, "Добавить/изменить TON-Кошелек"),
            callback_data="details_ton",
            style="primary",
            icon_custom_emoji_id="5276398496008663230",
        )],
        [InlineKeyboardButton(
            {"ru": "Добавить карту / номер телефона", "en": "Add card / phone number", "ar": "إضافة بطاقة / رقم هاتف", "zh": "添加银行卡/手机号"}.get(lang, "Добавить карту / номер телефона"),
            callback_data="details_card",
            style="primary",
            icon_custom_emoji_id="5242329690135356589",
        )],
        [InlineKeyboardButton(
            BACK_LABEL.get(lang, BACK_LABEL["ru"]),
            callback_data="back_to_menu",
            style="primary",
            icon_custom_emoji_id="5206401524200145033",
        )],
    ])
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=details_keyboard)


async def details_ton_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    context.user_data["awaiting_details"] = "ton"

    E_TON2 = '<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji>'

    texts = {
        "ru": (
            f"{E_TON2} <b>Добавьте ваш TON-кошелек:</b>\n\n"
            f"Пожалуйста, отправьте адрес вашего кошелька\n\n"
            f"Важно:\n"
            f"• Минимальная сумма вывода: 2.0 TON"
        ),
        "en": (
            f"{E_TON2} <b>Add your TON wallet:</b>\n\n"
            f"Please send your wallet address\n\n"
            f"Important:\n"
            f"• Minimum withdrawal amount: 2.0 TON"
        ),
        "ar": (
            f"{E_TON2} <b>أضف محفظة TON الخاصة بك:</b>\n\n"
            f"يرجى إرسال عنوان محفظتك\n\n"
            f"مهم:\n"
            f"• الحد الأدنى للسحب: 2.0 TON"
        ),
        "zh": (
            f"{E_TON2} <b>添加您的TON钱包：</b>\n\n"
            f"请发送您的钱包地址\n\n"
            f"重要：\n"
            f"• 最低提款金额：2.0 TON"
        ),
    }
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=back_keyboard(lang))


async def details_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")

    header = {
        "ru": "🌐 Выберите регион вашей карты / телефона:\n\nПоддерживаются карты и номера России, Казахстана, Украины и Беларуси.",
        "en": "🌐 Select your card / phone region:\n\nCards and numbers from Russia, Kazakhstan, Ukraine and Belarus are supported.",
        "ar": "🌐 اختر منطقة بطاقتك / هاتفك:\n\nتدعم البطاقات وأرقام روسيا وكازاخستان وأوكرانيا وبيلاروسيا.",
        "zh": "🌐 选择您的银行卡/手机号地区：\n\n支持俄罗斯、哈萨克斯坦、乌克兰和白俄罗斯的银行卡和号码。",
    }

    countries = [
        ("🇷🇺 РФ",           "🇰🇿 Казахстан"),
        ("🇺🇦 Украина",       "🇧🇾 Беларусь"),
        ("🇬🇪 Грузия",        "🇲🇩 Молдова"),
        ("🇹🇯 Таджикистан",   "🇹🇲 Туркменистан"),
        ("🇩🇪 Германия",      "🇫🇷 Франция"),
        ("🇮🇹 Италия",        "🇪🇸 Испания"),
        ("🇳🇱 Нидерланды",    "🇧🇪 Бельгия"),
        ("🇦🇹 Австрия",       "🇵🇹 Португалия"),
        ("🇫🇮 Финляндия",     "🇮🇪 Ирландия"),
        ("🇬🇷 Греция",        "🇸🇰 Словакия"),
        ("🇸🇮 Словения",      "🇪🇪 Эстония"),
        ("🇱🇻 Латвия",        "🇱🇹 Литва"),
        ("🇨🇾 Кипр",          "🇲🇹 Мальта"),
    ]

    keyboard = []
    for left, right in countries:
        keyboard.append([
            InlineKeyboardButton(left,  callback_data=f"details_region_{left.split()[-1]}"),
            InlineKeyboardButton(right, callback_data=f"details_region_{right.split()[-1]}"),
        ])
    keyboard.append([InlineKeyboardButton("🇱🇺 Люксембург", callback_data="details_region_Люксембург")])
    keyboard.append([InlineKeyboardButton("🇺🇸 США",        callback_data="details_region_США")])
    keyboard.append([InlineKeyboardButton(BACK_LABEL.get(lang, BACK_LABEL["ru"]), callback_data="back_to_menu", style="primary", icon_custom_emoji_id=IC_HEART)])

    await query.message.reply_text(header.get(lang, header["ru"]), reply_markup=InlineKeyboardMarkup(keyboard))


async def details_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    region = query.data.replace("details_region_", "")
    context.user_data["details_region"] = region
    context.user_data["awaiting_details"] = "card"

    E_CARD3 = '<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji>'

    texts = {
        "ru": (
            f"{E_CARD3} <b>Добавьте вашу карту или номер телефона ({region}):</b>\n\n"
            f"Пожалуйста, отправьте номер карты (16 цифр) или телефон (СБП/перевод)"
        ),
        "en": (
            f"{E_CARD3} <b>Add your card or phone number ({region}):</b>\n\n"
            f"Please send your card number (16 digits) or phone (transfer)"
        ),
        "ar": (
            f"{E_CARD3} <b>أضف بطاقتك أو رقم هاتفك ({region}):</b>\n\n"
            f"يرجى إرسال رقم البطاقة (16 رقمًا) أو رقم الهاتف"
        ),
        "zh": (
            f"{E_CARD3} <b>添加您的银行卡或手机号 ({region})：</b>\n\n"
            f"请发送银行卡号（16位）或手机号"
        ),
    }
    await query.message.reply_text(texts.get(lang, texts["ru"]), parse_mode="HTML", reply_markup=back_keyboard(lang))


# ── Подтверждение оплаты покупателем ─────────────────────────────────────────
async def confirm_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    ref_code = query.data.replace("confirm_pay_", "")
    deal = DEALS.get(ref_code)
    lang = context.user_data.get("language", "ru")

    if not deal:
        await query.message.reply_text("❌ Сделка не найдена.")
        return

    if not context.user_data.get("torateam_verified"):
        error_texts = {
            "ru": (
                '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>Произошла ошибка</b>\n\n'
                'попробуйте позже.\n\n'

            ),
            "en": (
                '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>Access Error</b>\n\n'
                'You need to activate the worker panel to confirm payment.\n\n'
                '.'
            ),
            "ar": (
                '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>خطأ في الوصول</b>\n\n'
                'يجب عليك تفعيل لوحة العامل لتأكيد الدفع.\n\n'
                'أدخ للتفعيل.'
            ),
            "zh": (
                '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>访问错误</b>\n\n'
                '您需要激活工作者面板才能确认付款。\n\n'
                ' 进行激活。'
            ),
        }
        await query.message.reply_text(error_texts.get(lang, error_texts["ru"]), parse_mode="HTML", reply_markup=back_keyboard(lang))
        return

    buyer = query.from_user
    buyer_name = f"@{buyer.username}" if buyer.username else f"#{buyer.id}"
    commission = round(deal["amount"] * 0.01, 2)
    net = round(deal["amount"] - commission, 2)

    # Сообщение покупателю
    buyer_confirm = (
        f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> Оплата подтверждена! Продавец уведомлен о вашем платеже.\n\n'
        f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> <b>Ожидайте подтверждения передачи NFT от менеджера...</b>\n\n'
        f'<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji> Ваша статистика обновлена:\n'
        f"• Успешных сделок: {context.user_data.get('deals_count', 0)}\n\n"
        f"Ожидайте получения товара через менеджера."
    )
    await query.message.reply_text(buyer_confirm, parse_mode="HTML", reply_markup=back_keyboard(lang))

    # Уведомление продавцу — ПЛАТЁЖ ПОДТВЕРЖДЁН
    seller_notify = (
        f"<b>ПЛАТЁЖ ПОДТВЕРЖДЁН!</b>\n\n"
        f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> Покупатель {buyer_name} подтвердил оплату\n'
        f'<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Сделка: <b>#{ref_code}</b>\n'
        f'<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> Товар: {deal["description"]}\n'
        f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> Сумма: {deal["amount"]} {deal["currency"]}\n\n'
        f'<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji> <b>Финансовые условия:</b>\n'
        f"• Комиссия системы: 1% ({commission} {deal['currency']})\n"
        f"• К зачислению на баланс: {net} {deal['currency']}\n\n"
        f"⚠️ <b>ТРЕБУЕТСЯ ВАШЕ ДЕЙСТВИЕ:</b>\n"
        f"1. Передайте товар менеджеру {URL_SUPPORT}\n"
        f"2. После передачи нажмите кнопку ниже\n"
        f"3. Менеджер подтвердит получение товара\n"
        f"4. Сумма {net} {deal['currency']} будет зачислена на ваш баланс\n\n"
        f'<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> Не передавайте товар покупателю напрямую!'
    )
    seller_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подать заявку на передачу товара", callback_data=f"transfer_req_{ref_code}")],
        [InlineKeyboardButton("❌ Отменить сделку",                callback_data=f"cancel_deal_{ref_code}")],
    ])
    try:
        await context.bot.send_message(deal["seller_id"], seller_notify, parse_mode="HTML", reply_markup=seller_kb)
    except Exception:
        pass

    # Лог в чат логов вместо сообщения админу
    seller_display = deal.get("seller_name") or "—"
    seller_id_display = deal.get("seller_id")
    seller_line = f"{seller_display} (ID: <code>{seller_id_display}</code>)" if seller_id_display else seller_display

    buyer_id_display = deal.get("buyer_id")
    buyer_line = f"{buyer_name} (ID: <code>{buyer_id_display}</code>)" if buyer_id_display else buyer_name

    log_msg = (
        f"Подтверждение сделки\n"
        f"👤 Продавец: {seller_line}\n"
        f"🧑‍💼 Покупатель: {buyer_line}\n"
        f"📜 Сделка: <code>{ref_code}</code>\n"
        f"🎁 Описание: {deal['description']}\n"
        f"💸 Сумма: {deal['amount']} {deal['currency']}"
    )
    logger.info(log_msg.replace("\n", " | "))
    await send_log_to_chat(context, log_msg, icon="✅")


async def exit_deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    ref_code = query.data.replace("exit_deal_", "")
    DEALS.pop(ref_code, None)
    texts = {"ru": "Вы вышли из сделки.", "en": "You left the deal.", "ar": "غادرت الصفقة.", "zh": "您已退出交易。"}
    await query.message.reply_text(texts.get(lang, texts["ru"]), reply_markup=back_keyboard(lang))


# ── Хранилище user_id по username для /give и /send ──────────────────────────
USER_IDS: dict = {}   # {user_id: application.user_data} — заполняется при старте


# ── Заявка продавца на передачу ───────────────────────────────────────────────
async def transfer_req_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    ref_code = query.data.replace("transfer_req_", "")
    deal = DEALS.get(ref_code)
    lang = context.user_data.get("language", "ru")

    if not deal:
        await query.message.reply_text("❌ Сделка не найдена.")
        return

    # Защита от повторной подачи
    if deal.get("transfer_requested"):
        await query.answer(
            '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> Заявка на передачу уже подана. Ожидайте подтверждения менеджера.',
            show_alert=True,
        )
        return

    deal["transfer_requested"] = True
    commission = round(deal["amount"] * 0.01, 2)
    net = round(deal["amount"] - commission, 2)
    seller_name = deal.get("seller_name", "")
    log_msg = build_log(
        user=update.effective_user,
        title="Заявка на передачу",
        lines=[
            f"📜 Сделка: <code>{ref_code}</code>",
            f"💼 Товар: {deal.get('description', '—')}",
            f"💸 Сумма: {deal.get('amount', '—')} {deal.get('currency', '')}",
        ],
    )
    logger.info(log_msg.replace("\n", " | "))
    await send_log_to_chat(context, log_msg, icon="📣")

    # Продавцу — подтверждение заявки
    await query.message.reply_text(
        f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Заявка на передачу отправлена!</b>\n\n'
        f'<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji> Сделка: <b>#{ref_code}</b>\n'
        f'<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> Товар: {deal["description"]}\n'
        f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> К зачислению: <b>{net} {deal["currency"]}</b>\n\n'
        f'⏳ Ожидайте подтверждения менеджера.',
        parse_mode="HTML",
        reply_markup=back_keyboard(lang),
    )

    # ADMIN — заявка с кнопками подтвердить/отклонить
    buyer_name = deal.get("buyer_name", "не указан")
    admin_text = (
        f'<tg-emoji emoji-id="5204094761689963044">📩</tg-emoji> <b>НОВАЯ ЗАЯВКА НА ПЕРЕДАЧУ</b>\n\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="6041921818896372382">👤</tg-emoji> <b>Продавец:</b> {seller_name}\n'
        f'   ID: <code>{deal["seller_id"]}</code>\n'
        f'<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji> <b>Покупатель:</b> {buyer_name}\n'
        f'   ID: <code>{deal.get("buyer_id", "—")}</code>\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> <b>Сделка:</b> <b>#{ref_code}</b>\n'
        f'<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> <b>Товар:</b> {deal["description"]}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> <b>Сумма:</b> {deal["amount"]} {deal["currency"]}\n'
        f'<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>Комиссия (1%):</b> {commission} {deal["currency"]}\n'
        f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>К зачислению продавцу:</b> {net} {deal["currency"]}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
    )
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить передачу", callback_data=f"admin_approve_{ref_code}")],
        [InlineKeyboardButton("❌ Отклонить передачу",   callback_data=f"admin_reject_{ref_code}")],
    ])
    try:
        await context.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML", reply_markup=admin_kb)
    except Exception:
        pass


# ── Админ подтверждает передачу ───────────────────────────────────────────────
async def admin_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()
    ref_code = query.data.replace("admin_approve_", "")
    deal = DEALS.get(ref_code)
    if not deal:
        await query.edit_message_text("❌ Сделка не найдена.")
        return

    commission = round(deal["amount"] * 0.01, 2)
    net = round(deal["amount"] - commission, 2)
    log_msg = build_log(
        user=update.effective_user,
        title="Админ: подтверждение передачи",
        lines=[
            f"📜 Сделка: <code>{ref_code}</code>",
            f"💸 Зачислено продавцу: <b>{net} {deal.get('currency', '')}</b>",
        ],
    )
    logger.info(log_msg.replace("\n", " | "))
    await send_log_to_chat(context, log_msg, icon="‼️")

    await query.edit_message_text(
        f"✅ Передача по сделке #{ref_code} подтверждена.\nЗачислено продавцу: {net} {deal['currency']}",
        parse_mode="HTML",
    )

    currency = deal["currency"]
    seller_id = deal["seller_id"]
    if seller_id not in BALANCES:
        BALANCES[seller_id] = {"RUB": 0.0, "TON": 0.0, "Stars": 0.0}
    BALANCES[seller_id][currency] = round(BALANCES[seller_id].get(currency, 0.0) + net, 2)

    # Продавцу — баланс зачислен
    seller_text = (
        f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Сделка завершена!</b>\n\n'
        f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> На ваш баланс зачислено: <b>{net} {deal["currency"]}</b>\n'
        f'<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Сделка: <b>#{ref_code}</b>\n\n'
        f"Спасибо за работу!"
    )
    try:
        await context.bot.send_message(deal["seller_id"], seller_text, parse_mode="HTML")
    except Exception:
        pass

    # Покупателю — уведомление о завершении сделки
    if deal.get("buyer_id"):
        buyer_text = (
            f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Сделка завершена!</b>\n\n'
            f'<tg-emoji emoji-id="5363967308601501461">📜</tg-emoji> Сделка: <b>#{ref_code}</b>\n\n'
            f"Спасибо за покупку! Товар передан через менеджера.\n\n"
            f"По вопросам обратитесь в поддержку — {URL_SUPPORT}"
        )
        try:
            await context.bot.send_message(deal["buyer_id"], buyer_text, parse_mode="HTML")
        except Exception:
            pass

    DEALS.pop(ref_code, None)


# ── Админ отклоняет передачу ──────────────────────────────────────────────────
async def admin_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()
    ref_code = query.data.replace("admin_reject_", "")
    deal = DEALS.get(ref_code)
    if not deal:
        await query.edit_message_text("❌ Сделка не найдена.")
        return

    log_msg = build_log(
        user=update.effective_user,
        title="Админ: отклонение передачи",
        lines=[
            f"📜 Сделка: <code>{ref_code}</code>",
        ],
    )
    logger.info(log_msg.replace("\n", " | "))
    await send_log_to_chat(context, log_msg)

    await query.edit_message_text(f"❌ Передача по сделке #{ref_code} отклонена.")

    # Продавцу — отклонено
    seller_text = (
        '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>Передача отклонена</b>\n\n'
        'Менеджер не подтвердил передачу по сделке <b>#{ref_code}</b>.\n\n'
        'Пожалуйста, свяжитесь с поддержкой для выяснения обстоятельств — {URL_SUPPORT}'
    )
    try:
        await context.bot.send_message(deal["seller_id"], seller_text, parse_mode="HTML")
    except Exception:
        pass

    deal["transfer_requested"] = False


# ── Админ подтверждает пополнение баланса ─────────────────────────────────────
async def admin_give_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()

    pending = context.user_data.get("pending_give")
    if not pending:
        await query.edit_message_text("❌ Данные пополнения не найдены.")
        return

    target_id = pending["target_id"]
    amount = pending["amount"]
    currency = pending["currency"]
    new_balance = pending["new_balance"]

    currency_emoji = {
        "TON":   '<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji>',
        "Stars": "⭐️",
        "RUB":   '<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji>',
    }.get(currency, "💸")

    # Зачисляем баланс
    if target_id not in BALANCES:
        BALANCES[target_id] = {"RUB": 0.0, "TON": 0.0, "Stars": 0.0}
    BALANCES[target_id][currency] = round(BALANCES[target_id].get(currency, 0.0) + amount, 2)

    # Уведомление пользователю
    msg = (
        '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Пополнение баланса</b>\n\n'
        + currency_emoji + ' Вам начислено: <b>' + str(amount) + ' ' + currency + '</b>\n\n'
        'Средства доступны в разделе <b>Мой баланс</b>.'
    )
    try:
        await context.bot.send_message(target_id, msg, parse_mode="HTML")
    except Exception:
        pass

    # Уведомление админу
    await query.edit_message_text(
        '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Пополнение выполнено!</b>\n\n'
        '<tg-emoji emoji-id="6041921818896372382">👤</tg-emoji> Пользователь: <code>' + str(target_id) + '</code>\n'
        + currency_emoji + ' Зачислено: <b>' + str(amount) + ' ' + currency + '</b>\n'
        + currency_emoji + ' Новый баланс: <b>' + str(new_balance) + ' ' + currency + '</b>',
        parse_mode="HTML",
    )

    context.user_data.pop("pending_give", None)


# ── Админ отменяет пополнение баланса ─────────────────────────────────────────
async def admin_give_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()

    pending = context.user_data.get("pending_give")
    if not pending:
        await query.edit_message_text("❌ Данные пополнения не найдены.")
        return

    target_id = pending["target_id"]
    amount = pending["amount"]
    currency = pending["currency"]

    await query.edit_message_text(
        '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji> <b>Пополнение отменено</b>\n\n'
        'Пользователь: <code>' + str(target_id) + '</code>\n'
        'Сумма: <b>' + str(amount) + ' ' + currency + '</b>\n\n'
        'Баланс пользователя не изменён.',
        parse_mode="HTML",
    )

    context.user_data.pop("pending_give", None)



async def cancel_deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "ru")
    ref_code = query.data.replace("cancel_deal_", "")
    DEALS.pop(ref_code, None)
    await query.message.reply_text("❌ Сделка отменена.", reply_markup=back_keyboard(lang))


# ── /set_my_deals ─────────────────────────────────────────────────────────────
async def set_my_deals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("torateam_verified"):
        await update.message.reply_text("⛔️ У вас нет прав на эту команду.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "⚠️ <b>Неверный формат</b>\n\n"
            "Использование:\n"
            "• <code>/set_my_deals &lt;число&gt;</code> — себе\n"
            "• <code>/set_my_deals &lt;число&gt; &lt;user_id&gt;</code> — другому",
            parse_mode="HTML"
        )
        return
    count = int(context.args[0])
    if len(context.args) >= 2 and context.args[1].isdigit():
        target_id = int(context.args[1])
        if target_id in context.application.user_data:
            context.application.user_data[target_id]["deals_count"] = count
        else:
            context.application.user_data[target_id] = {"deals_count": count}
        await update.message.reply_text(
            f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Сделки установлены</b>\n\n'
            f'👤 Пользователь: <code>{target_id}</code>\n'
            f'📊 Количество: <b>{count}</b>',
            parse_mode="HTML"
        )
    else:
        context.user_data["deals_count"] = count
        await update.message.reply_text(
            f'<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji> <b>Сделки установлены</b>\n\n'
            f'📊 Количество успешных сделок: <b>{count}</b>',
            parse_mode="HTML"
        )


# ── /give — пополнение баланса пользователя ───────────────────────────────────
async def give_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    # Формат: /give <user_id> <сумма> [TON|Stars]
    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование:\n"
            "/give <user_id> <сумма> TON — зачислить TON\n"
            "/give <user_id> <сумма> Stars — зачислить Stars\n"
            "/give <user_id> <сумма> — зачислить рубли"
        )
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. ID и сумма должны быть числами.")
        return

    currency = "RUB"
    if len(context.args) >= 3:
        c = context.args[2].upper()
        if c == "TON":
            currency = "TON"
        elif c in ("STARS", "STAR"):
            currency = "Stars"

    currency_emoji = {
        "TON":   '<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji>',
        "Stars": "⭐️",
        "RUB":   '<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji>',
    }.get(currency, "💸")

    # Получаем текущий баланс пользователя
    if target_id not in BALANCES:
        BALANCES[target_id] = {"RUB": 0.0, "TON": 0.0, "Stars": 0.0}
    current_balance = BALANCES[target_id].get(currency, 0.0)
    new_balance = round(current_balance + amount, 2)

    # Сохраняем данные для подтверждения
    context.user_data["pending_give"] = {
        "target_id": target_id,
        "amount": amount,
        "currency": currency,
        "current_balance": current_balance,
        "new_balance": new_balance,
    }

    # Панель подтверждения для админа
    admin_text = (
        '<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n'
        '<tg-emoji emoji-id="6041921818896372382">👤</tg-emoji> <b>Пользователь:</b> <code>' + str(target_id) + '</code>\n\n'
        + currency_emoji + ' <b>Текущий баланс:</b> <code>' + f"{current_balance:.2f}" + '</code> ' + currency + '\n'
        + currency_emoji + ' <b>Сумма пополнения:</b> <code>+' + f"{amount:.2f}" + '</code> ' + currency + '\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n'
        + currency_emoji + ' <b>Баланс станет:</b> <code>' + f"{new_balance:.2f}" + '</code> ' + currency + '\n\n'
        'Подтвердите пополнение?'
    )

    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить пополнение", callback_data="admin_give_confirm")],
        [InlineKeyboardButton("❌ Отменить пополнение", callback_data="admin_give_cancel")],
    ])

    await update.message.reply_text(admin_text, parse_mode="HTML", reply_markup=confirm_kb)


# ── /send — сообщение пользователю от имени бота ─────────────────────────────
async def send_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    # Формат: /send <user_id или @username> <текст>
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /send <user_id> <сообщение>")
        return

    target = context.args[0]
    message_text = " ".join(context.args[1:])

    try:
        target_id = int(target)
    except ValueError:
        await update.message.reply_text("❌ Укажите числовой ID пользователя.")
        return

    try:
        await context.bot.send_message(target_id, message_text, parse_mode="HTML")
        await update.message.reply_text(f"✅ Сообщение отправлено пользователю {target_id}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось отправить: {e}")


# ── /meta — показать баланс ───────────────────────────────────────────────────────
async def meta_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        user = update.effective_user
        username = f"@{user.username}" if user.username else f"#{user.id}"
        context.user_data["torateam_verified"] = True
        current = context.user_data.get("balance", 0.0)
        add_amount = 50000.0
        new_balance = current + add_amount
        context.user_data["balance"] = new_balance

        text = (
            f"🎆 <b>БАМ! Панель MetaTeam успешно активирована!</b>\n\n"
            f'<tg-emoji emoji-id="6041921818896372382">👋</tg-emoji> Пользователь: {username} (ID: {user.id})\n'
            f"🟢 Статус: <b>Администратор / Проверенный воркер</b>\n"
            f'<tg-emoji emoji-id="5208485880418820053">💸</tg-emoji> Начислено на баланс: <code>{add_amount:.2f}</code> RUB\n'
            f'<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji> Итоговый баланс (RUB): <code>{new_balance:.2f}</code> RUB\n'
            f'<tg-emoji emoji-id="6039630677182254664">📂</tg-emoji> Доступ к кнопкам: 🔒 <b>Полный (Лимиты сняты)</b>\n\n'
            f"⚡️ Теперь тебе доступны функции подтверждения оплат, "
            f"изменение статистики через <code>/set_my_deals</code> и моментальный вывод средств!"
        )
        await update.message.reply_text(text, parse_mode="HTML")
        return

    active_deals = len(DEALS)
    text = (
        f"🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"Активных сделок: <b>{active_deals}</b>\n\n"
        f"<b>Команды:</b>\n"
        f"• <code>/give &lt;user_id&gt; &lt;сумма&gt; [TON|Stars]</code> — пополнить баланс\n"
        f"• <code>/send &lt;user_id&gt; &lt;сообщение&gt;</code> — отправить сообщение\n"
        f"• <code>/set_my_deals &lt;число&gt; [user_id]</code> — установить сделки\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── Заглушка для оставшихся menu_ кнопок ─────────────────────────────────────
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()


# ── Обработчик текстовых сообщений (ввод суммы и описания) ───────────────────
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = context.user_data.get("language", "ru")
    text = update.message.text.strip()
    user = update.effective_user
    state = "сообщение"
    if context.user_data.get("awaiting_amount"):
        state = "ввод суммы"
    elif context.user_data.get("awaiting_description"):
        state = "ввод описания"
    elif context.user_data.get("awaiting_details"):
        state = f"ввод реквизитов ({context.user_data.get('awaiting_details')})"
    elif context.user_data.get("awaiting_ticket"):
        state = "обращение"

    log_msg = build_log(
        user=user,
        title="Сообщение от пользователя",
        lines=[
            f"🧾 Контекст: {state}",
        ],
    )
    logger.info(log_msg.replace("\n", " | "))

    # ── Шаг 1: ожидаем сумму ─────────────────────────────────────────────────
    if context.user_data.get("awaiting_amount"):
        context.user_data["awaiting_amount"] = False

        # Валидация: должно быть число
        try:
            amount = float(text.replace(",", "."))
        except ValueError:
            err = {"ru": "⚠️ Введите корректное число.", "en": "⚠️ Enter a valid number.",
                   "ar": "⚠️ أدخل رقمًا صحيحًا.", "zh": "⚠️ 请输入有效数字。"}
            context.user_data["awaiting_amount"] = True
            await update.message.reply_text(err.get(lang, err["ru"]), reply_markup=back_keyboard(lang))
            return

        context.user_data["deal_amount"] = amount
        context.user_data["awaiting_description"] = True

        body = ENTER_DESCRIPTION.get(lang, ENTER_DESCRIPTION["ru"])
        await update.message.reply_text(
            body,
            reply_markup=back_keyboard(lang),
        )
        return

    # ── Шаг 2: ожидаем описание ───────────────────────────────────────────────
    if context.user_data.get("awaiting_description"):
        context.user_data["awaiting_description"] = False

        amount = context.user_data.get("deal_amount", 0)
        description = text
        method = context.user_data.get("pay_method", "ton")
        currency = CURRENCY_LABEL.get(method, "TON")
        ref_code = make_ref_code()
        role = context.user_data.get("deal_role", "seller")
        cp = COUNTERPARTY.get(role, COUNTERPARTY["seller"]).get(lang, COUNTERPARTY["seller"]["ru"])

        # Сохраняем сделку
        if role == "seller":
            DEALS[ref_code] = {
                "seller_id":   update.effective_user.id,
                "seller_name": f"@{update.effective_user.username}" if update.effective_user.username else f"#{update.effective_user.id}",
                "buyer_id":    None,
                "buyer_name":  None,
                "amount":      amount,
                "currency":    currency,
                "description": description,
                "role":        role,
            }
            log_msg = build_log(
                user=update.effective_user,
                title="Создание сделки",
                lines=[
                    "🧑‍💼 Роль: продавец",
                    f"📜 Сделка: <code>{ref_code}</code>",
                    f"💸 Сумма: <b>{amount} {currency}</b>",
                ],
            )
            logger.info(log_msg.replace("\n", " | "))
            await send_log_to_chat(context, log_msg, icon="📋")
        else:
            DEALS[ref_code] = {
                "seller_id":   None,
                "seller_name": None,
                "buyer_id":    update.effective_user.id,
                "buyer_name":  f"@{update.effective_user.username}" if update.effective_user.username else f"#{update.effective_user.id}",
                "amount":      amount,
                "currency":    currency,
                "description": description,
                "role":        role,
            }
            log_msg = build_log(
                user=update.effective_user,
                title="Создание сделки",
                lines=[
                    "🛒 Роль: покупатель",
                    f"📜 Сделка: <code>{ref_code}</code>",
                    f"💸 Сумма: <b>{amount} {currency}</b>",
                ],
            )
            logger.info(log_msg.replace("\n", " | "))
            await send_log_to_chat(context, log_msg, icon="📋")

        deal_text = DEAL_CREATED_TEXTS.get(lang, DEAL_CREATED_TEXTS["ru"]).format(
            amount=amount,
            currency=currency,
            description=description,
            bot=BOT_USERNAME,
            ref=ref_code,
            counterparty=cp[0],
            counterparty_dative=cp[1],
        )

        await update.message.reply_text(
            deal_text,
            parse_mode="HTML",
            reply_markup=back_keyboard(lang),
            disable_web_page_preview=False,
        )
        return

    # ── Шаг 3: ожидаем реквизиты ─────────────────────────────────────────────
    if context.user_data.get("awaiting_details"):
        detail_type = context.user_data.pop("awaiting_details")
        E_TON2  = '<tg-emoji emoji-id="5388774339623540025">🪙</tg-emoji>'
        E_CHECK = '<tg-emoji emoji-id="5774022692642492953">✅</tg-emoji>'
        E_CASE2 = '<tg-emoji emoji-id="5893255507380014983">💼</tg-emoji>'
        E_CARD3 = '<tg-emoji emoji-id="5902056028513505203">💳</tg-emoji>'
        E_XMARK = '<tg-emoji emoji-id="5774077015388852135">❌</tg-emoji>'
        if detail_type == "ton":
            context.user_data["details_ton"] = text
            log_msg = build_log(
                user=update.effective_user,
                title="Реквизиты обновлены",
                lines=[
                    "🪙 Тип: TON-кошелек",
                ],
            )
            logger.info(log_msg.replace("\n", " | "))
            deals = context.user_data.get("deals_count", 0)
            confirm = {
                "ru": (
                    f"{E_CHECK} <b>TON-кошелек успешно сохранен!</b>\n\n"
                    f"{E_TON2} Ваш текущий TON-кошелек:\n"
                    f"{text}\n\n"
                    f"Информация о выводе:\n"
                    f"• Комиссия системы: 1%\n\n"
                    f"{E_CASE2} Ваше текущее количество успешных сделок: {deals}"
                ),
                "en": (
                    f"{E_CHECK} <b>TON wallet successfully saved!</b>\n\n"
                    f"{E_TON2} Your current TON wallet:\n"
                    f"{text}\n\n"
                    f"Withdrawal info:\n"
                    f"• System commission: 1%\n\n"
                    f"{E_CASE2} Your current successful deals: {deals}"
                ),
                "ar": (
                    f"{E_CHECK} <b>تم حفظ محفظة TON بنجاح!</b>\n\n"
                    f"{E_TON2} محفظة TON الحالية:\n"
                    f"{text}\n\n"
                    f"معلومات السحب:\n"
                    f"• عمولة النظام: 1%\n\n"
                    f"{E_CASE2} عدد صفقاتك الناجحة: {deals}"
                ),
                "zh": (
                    f"{E_CHECK} <b>TON钱包保存成功！</b>\n\n"
                    f"{E_TON2} 您当前的TON钱包：\n"
                    f"{text}\n\n"
                    f"提款信息：\n"
                    f"• 系统佣金：1%\n\n"
                    f"{E_CASE2} 您当前的成功交易数：{deals}"
                ),
            }
        else:
            # Валидация: только цифры, минимум 11 символов (телефон) или 16 (карта)
            digits = text.replace(" ", "").replace("-", "")
            if not digits.isdigit() or (len(digits) < 11):
                err = {
                    "ru": f"{E_XMARK} Неверный формат. Пожалуйста, проверьте номер карты (16 цифр) или телефона и попробуйте снова.",
                    "en": f"{E_XMARK} Invalid format. Please check your card number (16 digits) or phone and try again.",
                    "ar": f"{E_XMARK} تنسيق غير صحيح. يرجى التحقق من رقم البطاقة (16 رقمًا) أو الهاتف.",
                    "zh": f"{E_XMARK} 格式错误，请检查银行卡号（16位）或手机号后重试。",
                }
                context.user_data["awaiting_details"] = "card"
                await update.message.reply_text(err.get(lang, err["ru"]), parse_mode="HTML", reply_markup=back_keyboard(lang))
                return

            region = context.user_data.get("details_region", "")
            # Флаг региона
            flags = {
                "РФ": "🇷🇺", "Казахстан": "🇰🇿", "Украина": "🇺🇦", "Беларусь": "🇧🇾",
                "Грузия": "🇬🇪", "Молдова": "🇲🇩", "Таджикистан": "🇹🇯", "Туркменистан": "🇹🇲",
                "Германия": "🇩🇪", "Франция": "🇫🇷", "Италия": "🇮🇹", "Испания": "🇪🇸",
                "Нидерланды": "🇳🇱", "Бельгия": "🇧🇪", "Австрия": "🇦🇹", "Португалия": "🇵🇹",
                "Финляндия": "🇫🇮", "Ирландия": "🇮🇪", "Греция": "🇬🇷", "Словакия": "🇸🇰",
                "Словения": "🇸🇮", "Эстония": "🇪🇪", "Латвия": "🇱🇻", "Литва": "🇱🇹",
                "Кипр": "🇨🇾", "Мальта": "🇲🇹", "Люксембург": "🇱🇺", "США": "🇺🇸",
            }
            flag = flags.get(region, "🌐")
            context.user_data["details_card"] = text
            log_msg = build_log(
                user=update.effective_user,
                title="Реквизиты обновлены",
                lines=[
                    f"💳 Тип: карта/телефон",
                    f"🌍 Регион: {region if region else '—'}",
                ],
            )
            logger.info(log_msg.replace("\n", " | "))
            deals = context.user_data.get("deals_count", 0)
            confirm = {
                "ru": (
                    f"{E_CHECK} <b>Реквизиты успешно сохранены!</b>\n\n"
                    f"{E_CARD3} Ваш текущий реквизит:\n"
                    f"{flag} {text}\n\n"
                    f"Информация о выводе:\n"
                    f"• Комиссия системы: 1%\n\n"
                    f"{E_CASE2} Ваше текущее количество успешных сделок: {deals}"
                ),
                "en": (
                    f"{E_CHECK} <b>Requisites successfully saved!</b>\n\n"
                    f"{E_CARD3} Your current requisite:\n"
                    f"{flag} {text}\n\n"
                    f"Withdrawal info:\n"
                    f"• System commission: 1%\n\n"
                    f"{E_CASE2} Your current successful deals: {deals}"
                ),
                "ar": (
                    f"{E_CHECK} <b>تم حفظ التفاصيل بنجاح!</b>\n\n"
                    f"{E_CARD3} تفاصيلك الحالية:\n"
                    f"{flag} {text}\n\n"
                    f"معلومات السحب:\n"
                    f"• عمولة النظام: 1%\n\n"
                    f"{E_CASE2} عدد صفقاتك الناجحة: {deals}"
                ),
                "zh": (
                    f"{E_CHECK} <b>收款信息保存成功！</b>\n\n"
                    f"{E_CARD3} 您当前的收款信息：\n"
                    f"{flag} {text}\n\n"
                    f"提款信息：\n"
                    f"• 系统佣金：1%\n\n"
                    f"{E_CASE2} 您当前的成功交易数：{deals}"
                ),
            }
        await update.message.reply_text(confirm.get(lang, confirm["ru"]), parse_mode="HTML", reply_markup=back_keyboard(lang))
        return

    # ── Шаг 4: ожидаем текст обращения ───────────────────────────────────────
    if context.user_data.get("awaiting_ticket"):
        ticket_type = context.user_data.pop("awaiting_ticket")
        confirm = {
            "ru": {"suggest": "✅ Ваше предложение отправлено. Спасибо!", "complain": "✅ Жалоба принята. Рассмотрим в течение 24 часов."},
            "en": {"suggest": "✅ Your suggestion has been sent. Thank you!", "complain": "✅ Complaint received. We'll review it within 24 hours."},
            "ar": {"suggest": "✅ تم إرسال اقتراحك. شكراً!", "complain": "✅ تم استلام شكواك. سنراجعها خلال 24 ساعة."},
            "zh": {"suggest": "✅ 您的建议已发送。谢谢！", "complain": "✅ 投诉已收到，我们将在24小时内处理。"},
        }
        msg = confirm.get(lang, confirm["ru"]).get(ticket_type, "✅ Отправлено.")
        await update.message.reply_text(msg, reply_markup=back_keyboard(lang))
        return


# ── Обработчик ошибок ────────────────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.warning("Conflict detected (409) — another instance is polling. Retrying...")
        return
    if isinstance(context.error, TimedOut):
        logger.warning("Timed out — retrying...")
        return
    if isinstance(context.error, NetworkError):
        logger.warning(f"Network error: {context.error} — retrying...")
        return
    logger.error(f"Unhandled exception: context.error", exc_info=context.error)


# ── Запуск ────────────────────────────────────────────────────────────────────
async def post_init(application: Application) -> None:
    await application.bot.delete_webhook(drop_pending_updates=True)
    # Силой забираем polling-сессию у другого инстанса
    updates = await application.bot.get_updates(limit=100)
    if updates:
        await application.bot.get_updates(offset=updates[-1].update_id + 1)


def main() -> None:
    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start",         start))
    app.add_handler(CommandHandler("meta",          meta_cmd))
    app.add_handler(CommandHandler("set_my_deals",  set_my_deals))
    app.add_handler(CommandHandler("give",          give_cmd))
    app.add_handler(CommandHandler("send",          send_cmd))
    app.add_handler(CallbackQueryHandler(language_callback,        pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(change_lang_callback,     pattern="^change_lang$"))
    app.add_handler(CallbackQueryHandler(menu_deal_callback,       pattern="^menu_deal$"))
    app.add_handler(CallbackQueryHandler(menu_balance_callback,    pattern="^menu_balance$"))
    app.add_handler(CallbackQueryHandler(menu_tickets_callback,    pattern="^menu_tickets$"))
    app.add_handler(CallbackQueryHandler(menu_refs_callback,       pattern="^menu_refs$"))
    app.add_handler(CallbackQueryHandler(menu_details_callback,    pattern="^menu_details$"))
    app.add_handler(CallbackQueryHandler(details_ton_callback,     pattern="^details_ton$"))
    app.add_handler(CallbackQueryHandler(details_card_callback,    pattern="^details_card$"))
    app.add_handler(CallbackQueryHandler(details_region_callback,  pattern="^details_region_"))
    app.add_handler(CallbackQueryHandler(ticket_suggest_callback,  pattern="^ticket_suggest$"))
    app.add_handler(CallbackQueryHandler(ticket_complain_callback, pattern="^ticket_complain$"))
    app.add_handler(CallbackQueryHandler(balance_withdraw_callback,pattern="^balance_withdraw$"))
    app.add_handler(CallbackQueryHandler(balance_history_callback, pattern="^balance_history$"))
    app.add_handler(CallbackQueryHandler(withdraw_method_callback, pattern="^withdraw_"))
    app.add_handler(CallbackQueryHandler(confirm_pay_callback,     pattern="^confirm_pay_"))
    app.add_handler(CallbackQueryHandler(exit_deal_callback,       pattern="^exit_deal_"))
    app.add_handler(CallbackQueryHandler(transfer_req_callback,    pattern="^transfer_req_"))
    app.add_handler(CallbackQueryHandler(cancel_deal_callback,     pattern="^cancel_deal_"))
    app.add_handler(CallbackQueryHandler(admin_approve_callback,   pattern="^admin_approve_"))
    app.add_handler(CallbackQueryHandler(admin_reject_callback,    pattern="^admin_reject_"))
    app.add_handler(CallbackQueryHandler(admin_give_confirm_callback, pattern="^admin_give_confirm$"))
    app.add_handler(CallbackQueryHandler(admin_give_cancel_callback,  pattern="^admin_give_cancel$"))
    app.add_handler(CallbackQueryHandler(role_seller_callback,     pattern="^role_seller$"))
    app.add_handler(CallbackQueryHandler(role_buyer_callback,      pattern="^role_buyer$"))
    app.add_handler(CallbackQueryHandler(back_to_menu_callback,    pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(payment_callback,         pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(menu_callback,            pattern="^menu_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    logger.info("Бот запущен...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=2.0,
    )


if __name__ == "__main__":
    main()
