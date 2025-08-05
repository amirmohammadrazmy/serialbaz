import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import re
from flask import Flask, request
from asgiref.wsgi import WsgiToAsgi

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constants ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.fatal("FATAL: BOT_TOKEN environment variable is not set.")
    exit()

# --- Data Loading and Parsing ---
def parse_links(text: str) -> dict:
    series_data = {}
    pattern = re.compile(
        r"series/([^/]+)/Soft\.Sub/S(\d+)(?:/([^/]+))?(?:/([E|e]\d+))?"
    )
    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) != 2: continue
        download_link, info_link = parts[0].strip(), parts[1].strip()
        match = pattern.search(info_link)
        if match:
            series_name = match.group(1).replace('.', ' ').title()
            season = f"S{match.group(2)}"
            quality = match.group(3) if match.group(3) else "Standard"
            episode = match.group(4).upper() if match.group(4) else None
            series_data.setdefault(series_name, {}).setdefault(season, {})
            if episode:
                series_data[series_name][season].setdefault(quality, {})[episode] = download_link
            elif quality not in series_data[series_name][season]:
                series_data[series_name][season][quality] = download_link
    return series_data

def load_series_data() -> dict:
    try:
        with open("links.txt", "r", encoding="utf-8") as f:
            return parse_links(f.read())
    except FileNotFoundError:
        logger.error("CRITICAL: links.txt not found! The bot will not have any data.")
        return {}

# --- Telegram Bot Application Setup ---
application = Application.builder().token(BOT_TOKEN).build()

async def setup_bot():
    """Initializes the bot, loads data, and registers handlers."""
    await application.initialize()
    application.bot_data['series_data'] = load_series_data()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    application.add_handler(CallbackQueryHandler(button_callback))
    logger.info("Bot application initialized and handlers registered.")

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("خوش آمدید!\nبرای پیدا کردن سریال، نام آن را ارسال کنید.")

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.lower()
    series_data = context.bot_data.get('series_data', {})
    if not series_data:
        await update.message.reply_text("خطا: داده‌های سریال یافت نشد. لطفا وجود فایل links.txt را در سرور بررسی کنید.")
        return
    matches = {name: data for name, data in series_data.items() if query in name.lower()}
    if not matches:
        await update.message.reply_text("متاسفانه سریالی با این نام پیدا نشد.")
        return
    keyboard = [[InlineKeyboardButton(name, callback_data=f"srs_{name}")] for name in sorted(matches.keys())]
    await update.message.reply_text("نتایج یافت شده:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    series_data = context.bot_data.get('series_data', {})
    action, value = callback_data.split("_", 1)

    # A simple state machine using user_data
    if action == "srs":
        context.user_data['series_name'] = value
        seasons = sorted(series_data.get(value, {}).keys())
        keyboard = [[InlineKeyboardButton(f"فصل {s[1:]}", callback_data=f"sea_{s}")] for s in seasons]
        await query.edit_message_text(f"سریال: {value}\nفصل را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "sea":
        series_name = context.user_data.get('series_name')
        context.user_data['season_str'] = value
        qualities = sorted(series_data.get(series_name, {}).get(value, {}).keys())
        keyboard = [[InlineKeyboardButton(q, callback_data=f"qly_{q}")] for q in qualities]
        await query.edit_message_text(f"سریال: {series_name} - فصل {value[1:]}\nکیفیت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "qly":
        series_name = context.user_data.get('series_name')
        season_str = context.user_data.get('season_str')
        context.user_data['quality_str'] = value
        episode_data = series_data.get(series_name, {}).get(season_str, {}).get(value, {})
        if isinstance(episode_data, dict):
            episodes = sorted(episode_data.keys())
            keyboard = [[InlineKeyboardButton(f"قسمت {e[1:]}", callback_data=f"epi_{e}")] for e in episodes]
            await query.edit_message_text(f"سریال: {series_name} - ... - کیفیت {value}\nقسمت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [[InlineKeyboardButton("دانلود", url=episode_data)]]
            await query.edit_message_text(f"لینک دانلود برای {series_name} فصل {season_str[1:]} کیفیت {value}:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "epi":
        series_name = context.user_data.get('series_name')
        season_str = context.user_data.get('season_str')
        quality_str = context.user_data.get('quality_str')
        link = series_data.get(series_name, {}).get(season_str, {}).get(quality_str, {}).get(value)
        if link:
            keyboard = [[InlineKeyboardButton("دانلود قسمت", url=link)]]
            await query.edit_message_text(f"لینک دانلود قسمت {value[1:]}:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("خطا: لینک یافت نشد.")

# --- Web Server and Bot Integration ---
flask_app = Flask(__name__)

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
async def webhook_handler():
    update = Update.de_json(request.get_json(), application.bot)
    await application.process_update(update)
    return {"ok": True}

# Run the async setup function before defining the ASGI app
asyncio.run(setup_bot())

# The final object Uvicorn will run
app = WsgiToAsgi(flask_app)
