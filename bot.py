import telebot
import subprocess
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

user_data = {}

@bot.message_handler(commands=['start'])
def start_handler(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "السلام عليكم خاي Yasin Elämiri سيفط رابط rtmps:")
    user_data[chat_id] = {}

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text

    if chat_id not in user_data:
        bot.send_message(chat_id, "سيفط بعدا /start.")
        return

    if 'rtmps' not in user_data[chat_id]:
        if text.startswith("rtmps://"):
            user_data[chat_id]['rtmps'] = text
            bot.send_message(chat_id, "هكاك! دابا صيفط لي رابط M3U8:")
        else:
            bot.send_message(chat_id, "المرجو إدخال رابط RTMPS صحيح.")
    elif 'm3u8' not in user_data[chat_id]:
        if text.startswith("http") and text.endswith(".m3u8"):
            user_data[chat_id]['m3u8'] = text
            bot.send_message(chat_id, "بداية البث...")
            start_stream(chat_id)
        else:
            bot.send_message(chat_id, "المرجو إدخال رابط M3U8 صحيح.")
    else:
        bot.send_message(chat_id, "البث بدا بالفعل.")

def start_stream(chat_id):
    m3u8 = user_data[chat_id]['m3u8']
    rtmps = user_data[chat_id]['rtmps']
#تأكد من انك منزل المكتابة ffmpeg 
    command = [
        'ffmpeg',
        '-i', m3u8,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-f', 'flv',
        rtmps
    ]

    try:
        subprocess.Popen(command)
        bot.send_message(chat_id, "البث بدا بنجاح.")
    except Exception as e:
        bot.send_message(chat_id, f"وقعت شي مشكل: {str(e)}")

bot.polling()