import telebot
import requests
import os
import hashlib
import asyncio
import aiohttp
import sqlite3
import logging
import time
from telebot import types

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot Configuration
API_TOKEN = '7072873964:AAGiynaFyskvZRbJzcNLhRS9rNj5mHK35fE'
ADMIN_ID = '5934858568'
CHANNEL1_ID = '-1002190324709'
CHANNEL2_ID = '-1002157015735'
bot = telebot.TeleBot(API_TOKEN)

# Database Setup
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        telegram_id INTEGER UNIQUE,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        download_count INTEGER DEFAULT 0
    )
''')
conn.commit()

# --- Video Downloading Function ---

async def download_video(session, download_link, video_path):
    async with session.get(download_link) as response:
        with open(video_path, 'wb') as video_file:
            async for chunk in response.content.iter_chunked(1024):
                video_file.write(chunk)

def download_and_send_video(call, download_link):
    video_path = f"downloaded_{hashlib.md5(download_link.encode()).hexdigest()}.mp4"
    temp_msg = bot.send_message(call.message.chat.id, "Fetching. Please wait...")

    try:
        async def download_task():
            async with aiohttp.ClientSession() as session:
                await download_video(session, download_link, video_path)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(download_task())

        with open(video_path, 'rb') as video_file:
            markup = types.InlineKeyboardMarkup()
            share_button = types.InlineKeyboardButton('Share', switch_inline_query="Check out this cool video!")
            markup.add(share_button)

            bot.send_video(call.message.chat.id, video_file, reply_markup=markup)
            bot.send_video(ADMIN_ID, video_file, caption="New video downloaded by user.", reply_markup=markup)

            # Update download count
            cursor.execute("UPDATE users SET download_count = download_count + 1 WHERE telegram_id = ?", (call.from_user.id,))
            conn.commit()

    except Exception as e:
        log_error(f"Error sending video: {e}")
        bot.edit_message_text(f"Failed to download video: {e}", call.message.chat.id, temp_msg.message_id)
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        bot.delete_message(call.message.chat.id, temp_msg.message_id)


# --- Telegram Bot Handlers ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    cursor.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (user_id,))
    conn.commit()
    bot.send_message(CHANNEL2_ID, f"New user registered: {user_id}")

    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    download_button = types.KeyboardButton('Download Video')
    markup.add(download_button)
    bot.send_message(message.chat.id, "Welcome! Click the button below to download a video.", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == 'Download Video')
def ask_for_link(message):
    if is_user_banned(message.from_user.id):
        bot.reply_to(message, "You are banned.")
        return
    msg = bot.reply_to(message, "Please send me the video link.")
    bot.register_next_step_handler(msg, handle_video_link)

def handle_video_link(message):
    video_url = message.text
    bot.send_message(message.chat.id, "Fetching. Please wait...")
    try:
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Cookie': '_ga=GA1.1.1572978052.1718942380; __gads=ID=503a79b1f5760366:T=1718942378:RT=1718942378:S=ALNI_MZf9YbaRHm5SHuDLLgdTVwYVPu-lg; __gpi=UID=00000e580d753aee:T=1718942378:RT=1718942378:S=ALNI_MbDbtHT6kXik1HM4nIKQssRJ2eZGQ; __eoi=ID=4fab0d80f0a4afa7:T=1718942378:RT=1718942378:S=AA-AfjbSKW0Xj5LsrgihmfUKGr32; _ga_3Q4D9SLPKL=GS1.1.1718942380.1.1.1718942462.0.0.0; FCNEC=%5B%5B%22AKsRol90IryH66y0UuGmFClyNgM-CclcjD-YUflEdpCeLpA4CobXGy4kvgFOAKQ5SI3pTHuai1alJLe_yzj_oYyDU_0AkZe_NihW2L1oBDi3uBPu1YUPzlegD19Z6WIoZntW9HjMyBKo1MG3SDsf5y0Nz9jrjDQHxw%3D%3D',
            'Origin': 'https://ytshorts.savetube.me',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 12; M2004J19C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36',
            'sec-ch-ua': '"Not A(Brand";v="24", "Chromium";v="110", "Microsoft Edge Simulate";v="110", "Lemur";v="110"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"'
        }

        response = requests.post('https://ytshorts.savetube.me/api/v1/terabox-downloader', json={"url": video_url}, headers=headers)

        if response.status_code == 200:
            data = response.json().get('response', [])[0]
            thumbnail_url = data['thumbnail']
            title = data['title']
            download_link = data['resolutions']['Fast Download']

            callback_data = download_link[:64]

            markup = types.InlineKeyboardMarkup()
            download_button = types.InlineKeyboardButton('Download', callback_data=callback_data)
            markup.add(download_button)

            bot.send_photo(message.chat.id, thumbnail_url, caption=f"Title: {title}", reply_markup=markup)
            bot.send_message(CHANNEL1_ID, f"User {message.from_user.id} requested download: {download_link}")
        else:
            bot.send_message(message.chat.id, f"Failed to retrieve video details. Response:\n{response.text}")
    except Exception as e:
        log_error(f"Error handling video link: {e}")
        bot.send_message(message.chat.id, "Failed to process the video link. Please try again later.")

@bot.callback_query_handler(func=lambda call: True)
def handle_download(call):
    download_link = call.data
    try:
        download_and_send_video(call, download_link)
    except Exception as e:
        log_error(f"Error handling download: {e}")
        bot.send_message(call.message.chat.id, "Failed to process the download request. Please try again later.")

# --- Admin Commands ---

def is_user_admin(user_id):
    cursor.execute("SELECT is_admin FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()
    return result and result[0] == 1

@bot.message_handler(commands=['ban', 'unban', 'info', 'se', 'seall', 'help', 'elu'])
def handle_admin_commands(message):
    if not is_user_admin(message.from_user.id):
        return
    command = message.text.split()[0]
    args = message.text.split()[1:]

    if command in ['/ban', '.ban'] and len(args) == 1:
        user_id = args[0]
        cursor.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "You're banned from admin. If you want to be unbanned, contact @N2X4E✨")
        bot.reply_to(message, f"User {user_id} has been banned.")

    elif command in ['/unban', '.unban'] and len(args) == 1:
        user_id = args[0]
        cursor.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (user_id,))
        conn.commit()
        bot.reply_to(message, f"User {user_id} has been unbanned.")

    elif command in ['/info', '.info'] and len(args) == 1:
        user_id = args[0]
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        user_info = cursor.fetchone()
        if user_info:
            bot.reply_to(message, f"User Info:\nID: {user_info[0]}\nTelegram ID: {user_info[1]}\nAdmin: {bool(user_info[2])}\nBanned: {bool(user_info[3])}\nDownload Count: {user_info[4]}")
        else:
            bot.reply_to(message, "User not found.")

    elif command in ['/se', '.se'] and len(args) >= 2:
        user_id = args[0]
        msg_to_send = ' '.join(args[1:])
        bot.send_message(user_id, msg_to_send)
        bot.reply_to(message, f"Message sent to user {user_id}.")

    elif command in ['/seall', '.seall'] and len(args) >= 1:
        msg_to_send = ' '.join(args)
        cursor.execute("SELECT telegram_id FROM users")
        all_users = cursor.fetchall()
        for user in all_users:
            bot.send_message(user[0], msg_to_send)
        bot.reply_to(message, "Message sent to all users.")

    elif command in ['/help', '.help']:
        help_message = """
        /ban or .ban [user_id] - Ban a user
        /unban or .unban [user_id] - Unban a user
        /info or .info [user_id] - Get information about a user
        /se or .se [user_id] [message] - Send a message to a specific user
        /seall or .seall [message] - Send a message to all users
        /elu or .elu - Get a list of all admin commands
        """
        bot.reply_to(message, help_message)

    elif command in ['/elu', '.elu']:
        elu_message = """
        /ban or .ban [user_id] - Ban a user
        /unban or .unban [user_id] - Unban a user
        /info or .info [user_id] - Get information about a user
        /se or .se [user_id] [message] - Send a message to a specific user
        /seall or .seall [message] - Send a message to all users
        /help or .help - Get help on admin commands
        /elu or .elu - Get a list of all admin commands
        """
        bot.send_message(ADMIN_ID, elu_message, disable_notification=False)
        bot.pin_chat_message(ADMIN_ID, message.message_id)

def is_user_banned(user_id):
    cursor.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()
    return result and result[0] == 1

# --- Utility Functions ---

def log_error(message):
    logging.error(message)
    bot.send_message(ADMIN_ID, f"Error: {message}")

# --- Start the Bot ---

# Error Handler for Uncaught Exceptions
def handle_exception(exception):
    logging.error(f"Uncaught exception: {exception}")
    bot.send_message(ADMIN_ID, f"Error: {exception}")

while True:
    try:
        bot.polling(none_stop=True, timeout=30)
    except Exception as e:
        handle_exception(e)
        time.sleep(5) 
