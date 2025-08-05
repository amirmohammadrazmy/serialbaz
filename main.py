import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import re

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_token():
    """Reads the bot token from bot_token.txt."""
    try:
        with open("bot_token.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error("bot_token.txt not found. Please create this file and add your bot token to it.")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /start is issued."""
    await update.message.reply_text(
        "Welcome to the Series Downloader Bot!\n\n"
        "Please send me a text file with download links to get started.\n"
        "The links should be in the format:\n"
        "download_link | info_link\n\n"
        "For example:\n"
        "https://2ad.ir/L9SfXRk | https://.../Young.Justice/Soft.Sub/S04/\n"
        "or\n"
        "https://2ad.ir/L9SfXRk | https://.../Young.Justice/Soft.Sub/S04/480p/E01.mkv"
    )

def parse_links(text: str) -> dict:
    """Parses the text and extracts series info."""
    series_data = {}
    episode_pattern = re.compile(r"series/([^/]+)/Soft\.Sub/S(\d+)/[^/]+/([E|e]\d+)")
    season_pattern = re.compile(r"series/([^/]+)/Soft\.Sub/S(\d+)")

    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) != 2:
            continue

        download_link = parts[0].strip()
        info_link = parts[1].strip()

        episode_match = episode_pattern.search(info_link)
        if episode_match:
            series_name = episode_match.group(1)
            season = f"S{episode_match.group(2)}"
            episode = episode_match.group(3).upper()

            if series_name not in series_data:
                series_data[series_name] = {}
            if season not in series_data[series_name]:
                series_data[series_name][season] = {}
            series_data[series_name][season][episode] = download_link
            continue

        season_match = season_pattern.search(info_link)
        if season_match:
            series_name = season_match.group(1)
            season = f"S{season_match.group(2)}"

            if series_name not in series_data:
                series_data[series_name] = {}
            series_data[series_name][season] = download_link

    return series_data

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the uploaded text file."""
    document = update.message.document
    if document.mime_type == "text/plain":
        file = await document.get_file()
        file_content = (await file.download_as_bytearray()).decode("utf-8")

        series_data = parse_links(file_content)
        context.user_data['series_data'] = series_data

        if not series_data:
            await update.message.reply_text("No valid links found in the file.")
            return

        keyboard = []
        for series_name in sorted(series_data.keys()):
            button = InlineKeyboardButton(series_name, callback_data=f"series_{series_name}")
            keyboard.append([button])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Please choose a series:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please upload a .txt file.")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    series_data = context.user_data.get('series_data', {})

    if callback_data.startswith("series_"):
        series_name = callback_data.split("_", 1)[1]
        context.user_data['selected_series'] = series_name

        seasons = sorted(series_data.get(series_name, {}).keys())
        keyboard = []
        for season in seasons:
            button = InlineKeyboardButton(season, callback_data=f"season_{season}")
            keyboard.append([button])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"Selected Series: {series_name}\nPlease choose a season:", reply_markup=reply_markup)

    elif callback_data.startswith("season_"):
        season = callback_data.split("_", 1)[1]
        series_name = context.user_data.get('selected_series')
        season_data = series_data.get(series_name, {}).get(season, {})

        if isinstance(season_data, dict): # It has episodes
            episodes = sorted(season_data.keys())
            keyboard = []
            for episode in episodes:
                button = InlineKeyboardButton(episode, callback_data=f"episode_{season}_{episode}")
                keyboard.append([button])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=f"Selected Season: {season}\nPlease choose an episode:", reply_markup=reply_markup)
        else: # It's a direct download link
            link = season_data
            keyboard = [[InlineKeyboardButton("Download Season", url=link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=f"Download link for {series_name} {season}:", reply_markup=reply_markup)

    elif callback_data.startswith("episode_"):
        _, season, episode = callback_data.split("_", 2)
        series_name = context.user_data.get('selected_series')

        link = series_data.get(series_name, {}).get(season, {}).get(episode)
        if link:
            keyboard = [[InlineKeyboardButton("Download", url=link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=f"Download link for {series_name} {season} {episode}:", reply_markup=reply_markup)
        else:
            await query.edit_message_text(text="Sorry, download link not found.")

def main() -> None:
    """Start the bot."""
    token = get_token()
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Bot token not found or is a placeholder. Please update bot_token.txt.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(token).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.TEXT, handle_file))
    application.add_handler(CallbackQueryHandler(button))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()
