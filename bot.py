import os
import subprocess
import telebot
from dotenv import load_dotenv
from flask import Flask
import threading

# تحميل المتغيرات
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# إعداد البوت و Flask
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_data = {}

@app.route('/')
def index():
    return '✅ البوت شغال على Railway!'

def telegram_bot():
    @bot.message_handler(commands=['start'])
    def start_handler(message):
        chat_id = message.chat.id
        user_data[chat_id] = {}
        bot.send_message(chat_id, "✋ السلام عليكم! سيفط لي Stream Key ديال Facebook.")

    @bot.message_handler(func=lambda message: True)
    def handle_message(message):
        chat_id = message.chat.id
        text = message.text.strip()

        if chat_id not in user_data:
            bot.send_message(chat_id, "سيفط /start الأول.")
            return

        if 'stream_key' not in user_data[chat_id]:
            user_data[chat_id]['stream_key'] = text
            bot.send_message(chat_id, "✅ دابا سيفط رابط M3U8.")
            return

        if 'm3u8' not in user_data[chat_id]:
            if text.startswith("http") and text.endswith(".m3u8"):
                user_data[chat_id]['m3u8'] = text
                bot.send_message(chat_id, "🚀 جاري بدء البث...")
                start_stream(chat_id)
            else:
                bot.send_message(chat_id, "❌ رابط M3U8 غير صالح.")
            return

        bot.send_message(chat_id, "✅ راه البث بدا، إذا بغيت تبدل شي حاجة سيفط /start.")

    def start_stream(chat_id):
        m3u8 = user_data[chat_id]['m3u8']
        stream_key = user_data[chat_id]['stream_key']
        rtmps_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{stream_key}"

        command = [
            'ffmpeg',
            '-re',
            '-i', m3u8,
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-b:v', '3000k',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            rtmps_url
        ]

        try:
            subprocess.Popen(command)
            bot.send_message(chat_id, "✅ البث بدا على Facebook Live.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ خطأ في البث: {str(e)}")

    bot.infinity_polling()

# تشغيل Flask و bot في نفس الوقت
if __name__ == "__main__":
    threading.Thread(target=telegram_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))