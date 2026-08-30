import os
from dotenv import load_dotenv

load_dotenv()

# ── Настройки бота (из .env) ───────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")

# ── Ссылки ──────────────────────────────────────────────────────────────────
URL_CHANNEL    = "https://t.me/Playerok"
URL_SUPPORT    = os.getenv("URL_SUPPORT")
URL_MINI_APP   = "https://playerok.com"

# ── Пути к изображениям по языкам ───────────────────────────────────────────────
# Если изображение для конкретного языка отсутствует, используется значение по умолчанию (оригинальное .jpg)
LOGO_PATH = {
    "ru": "menu.jpg",  # по умолчанию для русского - оригинал
    "en": "menu_en.jpg",
    "ar": "menu_ar.jpg",
    "zh": "menu_zh.jpg",
    "default": "menu.jpg"  # запасной вариант
}
IMG_DEAL = {
    "ru": "deal.jpg",
    "en": "deal_en.jpg",
    "ar": "deal_ar.jpg",
    "zh": "deal_zh.jpg",
    "default": "deal.jpg"
}
IMG_BALANCE = {
    "ru": "balance.jpg",
    "en": "balance_en.jpg",
    "ar": "balance_ar.jpg",
    "zh": "balance_zh.jpg",
    "default": "balance.jpg"
}
IMG_DETAILS = {
    "ru": "details.jpg",
    "en": "details_en.jpg",
    "ar": "details_ar.jpg",
    "zh": "details_zh.jpg",
    "default": "details.jpg"
}
IMG_TICKETS = {
    "ru": "tickets.jpg",
    "en": "tickets_en.jpg",
    "ar": "tickets_ar.jpg",
    "zh": "tickets_zh.jpg",
    "default": "tickets.jpg"
}
