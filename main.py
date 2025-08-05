import logging
import os
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
# Render will set the BOT_TOKEN from the environment variables you configure.
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Render provides the PORT, or we default to 8000 for local testing.
PORT = int(os.environ.get('PORT', 8000))
# The WEBHOOK_URL is your Render service's public URL.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# --- Data Loading and Parsing ---
def parse_links(text: str) -> dict:
    """
    Parses text from links.txt into a nested dictionary.
    Structure: series -> season -> quality -> episode -> link
    """
    series_data = {}
    pattern = re.compile(
        r"series/([^/]+)/Soft\.Sub/S(\d+)(?:/([^/]+))?(?:/([E|e]\d+))?"
    )

    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) != 2:
            continue

        download_link = parts[0].strip()
        info_link = parts[1].strip()
        match = pattern.search(info_link)

        if match:
            series_name = match.group(1).replace('.', ' ').title()
            season = f"S{match.group(2)}"
            # Use a placeholder if quality is not present in the URL
            quality = match.group(3) if match.group(3) else "Standard"
            episode = match.group(4).upper() if match.group(4) else None

            series_data.setdefault(series_name, {})
            series_data[series_name].setdefault(season, {})

            if episode:
                series_data[series_name][season].setdefault(quality, {})
                series_data[series_name][season][quality][episode] = download_link
            else:
                # If no episode, the link is for the quality level itself.
                # If a link for this quality already exists, we don't overwrite it
                # (assuming the first link found for a quality level is the main one).
                if quality not in series_data[series_name][season]:
                    series_data[series_name][season][quality] = download_link
    return series_data

def load_series_data() -> dict:
    """Loads and parses the links.txt file."""
    try:
        with open("links.txt", "r", encoding="utf-8") as f:
            text = f.read()
            return parse_links(text)
    except FileNotFoundError:
        logger.error("links.txt not found! Please create it and add links.")
        return {}

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
    await update.message.reply_text(
        "خوش آمدید!\n"
        "برای پیدا کردن سریال مورد نظر، نام آن را تایپ و ارسال کنید."
    )

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles user search query."""
    query = update.message.text.lower()
    series_data = context.bot_data.get('series_data', {})
    matches = {name: data for name, data in series_data.items() if query in name.lower()}

    if not matches:
        await update.message.reply_text("متاسفانه سریالی با این نام پیدا نشد. لطفا دوباره تلاش کنید.")
        return

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"srs_{name}")] for name in sorted(matches.keys())
    ]
    await update.message.reply_text("نتایج یافت شده:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses all callback queries."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    series_data = context.bot_data.get('series_data', {})
    action, value = callback_data.split("_", 1)

    if action == "srs":
        series_name = value
        context.user_data['series_name'] = series_name
        seasons = sorted(series_data.get(series_name, {}).keys())
        keyboard = [[InlineKeyboardButton(f"فصل {s[1:]}", callback_data=f"sea_{s}")] for s in seasons]
        await query.edit_message_text(f"سریال: {series_name}\nفصل را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "sea":
        season_str = value
        series_name = context.user_data.get('series_name')
        context.user_data['season_str'] = season_str
        qualities = sorted(series_data.get(series_name, {}).get(season_str, {}).keys())
        keyboard = [[InlineKeyboardButton(q, callback_data=f"qly_{q}")] for q in qualities]
        await query.edit_message_text(f"سریال: {series_name} - فصل {season_str[1:]}\nکیفیت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "qly":
        quality_str = value
        series_name = context.user_data.get('series_name')
        season_str = context.user_data.get('season_str')
        context.user_data['quality_str'] = quality_str
        episode_data = series_data.get(series_name, {}).get(season_str, {}).get(quality_str, {})

        if isinstance(episode_data, dict):
            episodes = sorted(episode_data.keys())
            keyboard = [[InlineKeyboardButton(f"قسمت {e[1:]}", callback_data=f"epi_{e}")] for e in episodes]
            await query.edit_message_text(f"سریال: {series_name} - ... - کیفیت {quality_str}\nقسمت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            link = episode_data
            keyboard = [[InlineKeyboardButton("دانلود", url=link)]]
            await query.edit_message_text(f"لینک دانلود برای {series_name} فصل {season_str[1:]} کیفیت {quality_str}:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "epi":
        episode_str = value
        series_name = context.user_data.get('series_name')
        season_str = context.user_data.get('season_str')
        quality_str = context.user_data.get('quality_str')
        link = series_data.get(series_name, {}).get(season_str, {}).get(quality_str, {}).get(episode_str)
        if link:
            keyboard = [[InlineKeyboardButton("دانلود قسمت", url=link)]]
            await query.edit_message_text(f"لینک دانلود قسمت {episode_str[1:]}:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("خطا: لینک یافت نشد.")

# --- Main Application Setup ---
if not BOT_TOKEN:
    logger.fatal("FATAL: BOT_TOKEN environment variable is not set.")
    # Exit if no token is found, to prevent the app from running without a bot.
    exit()

# Initialize the Telegram Application
application = Application.builder().token(BOT_TOKEN).build()
telegram_bot = application.bot
application.bot_data['series_data'] = load_series_data()

# Register Telegram handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
application.add_handler(CallbackQueryHandler(button_callback))

# --- Flask Web Server and ASGI Adapter ---
# Create a standard Flask app
flask_app = Flask(__name__)

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
async def webhook_handler():
    """Handle incoming updates from Telegram."""
    # request.get_json() is not an async function, so we don't await it.
    update_data = request.get_json()
    update = Update.de_json(update_data, telegram_bot)
    await application.process_update(update)
    return {"ok": True}

# Wrap the Flask WSGI app in the AsgiToWsgi adapter
app = WsgiToAsgi(flask_app)

# Note: The `if __name__ == "__main__":` block is removed
# because the app is run by an ASGI server like Uvicorn, not by executing the script directly.
# The server will be started with a command like:
# uvicorn main:app --host 0.0.0.0 --port 10000
