import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import re
from flask import Flask, request

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constants ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get('PORT', 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# --- Data Loading and Parsing ---
def parse_links(text: str) -> dict:
    """
    Parses text from links.txt into a nested dictionary.
    Structure: series -> season -> quality -> episode -> link
    Handles links with missing quality or episode levels.
    """
    series_data = {}
    # Pattern captures: 1:Series, 2:Season, 3:Quality, 4:Episode
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
            quality = match.group(3) if match.group(3) else "Unknown"
            episode = match.group(4).upper() if match.group(4) else None

            # Create nested dictionaries if they don't exist
            series_data.setdefault(series_name, {})
            series_data[series_name].setdefault(season, {})

            if episode:
                series_data[series_name][season].setdefault(quality, {})
                series_data[series_name][season][quality][episode] = download_link
            else:
                # If no episode, the link is for the quality level (or season if quality is also missing)
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
    """Sends a welcome message and prompts for a search."""
    await update.message.reply_text(
        "خوش آمدید!\n"
        "برای پیدا کردن سریال مورد نظر، نام آن را تایپ و ارسال کنید."
    )

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles user text input as a search query."""
    query = update.message.text.lower()
    series_data = context.bot_data.get('series_data', {})
    matches = {name: data for name, data in series_data.items() if query in name.lower()}

    if not matches:
        await update.message.reply_text("متاسفانه سریالی با این نام پیدا نشد. لطفا دوباره تلاش کنید.")
        return

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"srs_{name[:20]}")] for name in sorted(matches.keys())
    ]
    await update.message.reply_text("نتایج یافت شده:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses all callback queries from inline buttons."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    series_data = context.bot_data.get('series_data', {})

    # Using prefixes for different levels: srs, sea, qly, epi
    action, value = callback_data.split("_", 1)

    if action == "srs":
        series_name = value
        context.user_data['series_name'] = series_name
        seasons = sorted(series_data.get(series_name, {}).keys())
        keyboard = [
            [InlineKeyboardButton(f"فصل {s[1:]}", callback_data=f"sea_{s}")] for s in seasons
        ]
        await query.edit_message_text(f"سریال: {series_name}\nفصل را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "sea":
        season_str = value
        series_name = context.user_data.get('series_name')
        context.user_data['season_str'] = season_str
        qualities = sorted(series_data.get(series_name, {}).get(season_str, {}).keys())
        keyboard = [
            [InlineKeyboardButton(q, callback_data=f"qly_{q}")] for q in qualities
        ]
        await query.edit_message_text(f"سریال: {series_name} - فصل {season_str[1:]}\nکیفیت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "qly":
        quality_str = value
        series_name = context.user_data.get('series_name')
        season_str = context.user_data.get('season_str')
        episode_data = series_data.get(series_name, {}).get(season_str, {}).get(quality_str, {})

        if isinstance(episode_data, dict): # It has episodes
            episodes = sorted(episode_data.keys())
            keyboard = [
                [InlineKeyboardButton(f"قسمت {e[1:]}", callback_data=f"epi_{quality_str}_{e}")] for e in episodes
            ]
            await query.edit_message_text(f"سریال: {series_name} - فصل {season_str[1:]} - کیفیت {quality_str}\nقسمت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        else: # It's a direct download link
            link = episode_data
            keyboard = [[InlineKeyboardButton("دانلود", url=link)]]
            await query.edit_message_text(f"لینک دانلود برای {series_name} فصل {season_str[1:]} کیفیت {quality_str}:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "epi":
        quality_str, episode_str = value.split("_", 1)
        series_name = context.user_data.get('series_name')
        season_str = context.user_data.get('season_str')
        link = series_data.get(series_name, {}).get(season_str, {}).get(quality_str, {}).get(episode_str)
        if link:
            keyboard = [[InlineKeyboardButton("دانلود قسمت", url=link)]]
            await query.edit_message_text(f"لینک دانلود قسمت {episode_str[1:]} از فصل {season_str[1:]}:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("خطا: لینک یافت نشد.")

# --- Flask Web Server for Webhook ---
app = Flask(__name__)

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
async def webhook_handler():
    """Sets up the webhook and handles updates from Telegram."""
    update_data = request.get_json()
    update = Update.de_json(update_data, telegram_bot)
    await application.process_update(update)
    return {"ok": True}

# --- Main Application Setup ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.fatal("FATAL: BOT_TOKEN environment variable is not set.")
    else:
        application = Application.builder().token(BOT_TOKEN).build()
        telegram_bot = application.bot

        # Load data into bot_data
        application.bot_data['series_data'] = load_series_data()
        if not application.bot_data['series_data']:
            logger.warning("Series data is empty. Bot might not work as expected.")

        # Register handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
        application.add_handler(CallbackQueryHandler(button_callback))

        # We run the Flask app instead of application.run_polling()
        # The setup of the webhook is handled by Render's startup command.
        # It's assumed a command like `gunicorn main:app` or similar will be used.
        # For local testing, you would run this script directly and set up the webhook manually.
        app.run(host="0.0.0.0", port=PORT)
