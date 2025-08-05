import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import re

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Data Loading ---
def parse_links(text: str) -> dict:
    """Parses the text from links.txt and extracts series info."""
    series_data = {}
    # Regex to find .../series/SERIESNAME/Soft.Sub/SXX/.../EXX
    episode_pattern = re.compile(r"series/([^/]+)/Soft\.Sub/S(\d+)/[^/]+/([E|e]\d+)")
    # Regex to find .../series/SERIESNAME/Soft.Sub/SXX
    season_pattern = re.compile(r"series/([^/]+)/Soft\.Sub/S(\d+)")

    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) != 2:
            continue

        download_link = parts[0].strip()
        info_link = parts[1].strip()

        # Try to match the more specific episode pattern first
        episode_match = episode_pattern.search(info_link)
        if episode_match:
            series_name = episode_match.group(1).replace('.', ' ').title()
            season = f"S{episode_match.group(2)}"
            episode = episode_match.group(3).upper()

            if series_name not in series_data:
                series_data[series_name] = {}
            if season not in series_data[series_name] or not isinstance(series_data[series_name][season], dict):
                series_data[series_name][season] = {}
            series_data[series_name][season][episode] = download_link
            continue

        # Fallback to matching the season pattern
        season_match = season_pattern.search(info_link)
        if season_match:
            series_name = season_match.group(1).replace('.', ' ').title()
            season = f"S{season_match.group(2)}"

            if series_name not in series_data:
                series_data[series_name] = {}
            # Only set the season link if it hasn't been set to a dict of episodes already
            if season not in series_data[series_name]:
                 series_data[series_name][season] = download_link

    return series_data

def load_series_data() -> dict:
    """Loads and parses the links.txt file."""
    try:
        with open("links.txt", "r") as f:
            text = f.read()
            return parse_links(text)
    except FileNotFoundError:
        logger.error("links.txt not found. Please create this file and add links to it.")
        return {}

# --- Command and Message Handlers ---
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

    # Basic search: find series names containing the query
    matches = {name: data for name, data in series_data.items() if query in name.lower()}

    if not matches:
        await update.message.reply_text("متاسفانه سریالی با این نام پیدا نشد. لطفا دوباره تلاش کنید.")
        return

    keyboard = []
    for series_name in sorted(matches.keys()):
        # Callback data should be robust enough not to exceed Telegram limits
        button = InlineKeyboardButton(series_name, callback_data=f"series_{series_name}")
        keyboard.append([button])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("نتایج یافت شده:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    series_data = context.bot_data.get('series_data', {})

    # --- Series Selection ---
    if callback_data.startswith("series_"):
        series_name = callback_data.split("_", 1)[1]
        context.user_data['selected_series'] = series_name

        seasons = sorted(series_data.get(series_name, {}).keys())
        keyboard = []
        for season in seasons:
            button = InlineKeyboardButton(f"فصل {season[1:]}", callback_data=f"season_{season}")
            keyboard.append([button])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"سریال: {series_name}\nفصل مورد نظر را انتخاب کنید:", reply_markup=reply_markup)

    # --- Season Selection ---
    elif callback_data.startswith("season_"):
        season_str = callback_data.split("_", 1)[1]
        series_name = context.user_data.get('selected_series')
        if not series_name:
            await query.edit_message_text(text="خطا: سریال انتخاب شده یافت نشد. لطفا از ابتدا شروع کنید.")
            return

        season_data = series_data.get(series_name, {}).get(season_str, {})

        if isinstance(season_data, dict): # This season has episodes
            episodes = sorted(season_data.keys())
            keyboard = []
            for episode in episodes:
                button = InlineKeyboardButton(f"قسمت {episode[1:]}", callback_data=f"episode_{season_str}_{episode}")
                keyboard.append([button])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=f"سریال: {series_name} - فصل {season_str[1:]}\nقسمت مورد نظر را انتخاب کنید:", reply_markup=reply_markup)
        else: # This is a direct download link for the whole season
            link = season_data
            keyboard = [[InlineKeyboardButton("دانلود کل فصل", url=link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=f"لینک دانلود فصل {season_str[1:]} از سریال {series_name}:", reply_markup=reply_markup)

    # --- Episode Selection ---
    elif callback_data.startswith("episode_"):
        _, season_str, episode_str = callback_data.split("_", 2)
        series_name = context.user_data.get('selected_series')
        if not series_name:
            await query.edit_message_text(text="خطا: سریال انتخاب شده یافت نشد. لطفا از ابتدا شروع کنید.")
            return

        link = series_data.get(series_name, {}).get(season_str, {}).get(episode_str)
        if link:
            keyboard = [[InlineKeyboardButton("دانلود قسمت", url=link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=f"لینک دانلود قسمت {episode_str[1:]} از فصل {season_str[1:]} سریال {series_name}:", reply_markup=reply_markup)
        else:
            await query.edit_message_text(text="خطا: لینک دانلود یافت نشد.")

# --- Main Bot Setup ---
def get_token():
    """Reads the bot token from bot_token.txt."""
    try:
        with open("bot_token.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error("bot_token.txt not found. Please create this file and add your bot token to it.")
        return None

def main() -> None:
    """Start the bot."""
    token = get_token()
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Bot token not found or is a placeholder. Please update bot_token.txt.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(token).build()

    # Load data into bot_data so it's accessible everywhere
    application.bot_data['series_data'] = load_series_data()
    if not application.bot_data['series_data']:
        logger.warning("Series data is empty. The bot might not work as expected.")

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()
