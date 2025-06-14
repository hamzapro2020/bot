import os
import subprocess
import telebot
from dotenv import load_dotenv
from flask import Flask
import threading

# تحميل متغيرات البيئة
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# إعداد البوت و Flask
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_data = {}

@app.route('/')
def index():
    return '🤖 البوت شغال - Facebook Stream Bot'

def run_bot():
    @bot.message_handler(commands=['start'])
    def start_handler(message):
        chat_id = message.chat.id
        user_data[chat_id] = {}
        bot.send_message(chat_id, "👋 السلام عليكم!\nسيفط ليا *Facebook Stream Key* فقط (ماشي الرابط كامل).", parse_mode="Markdown")

    @bot.message_handler(func=lambda message: True)
    def handle_message(message):
        chat_id = message.chat.id
        text = message.text.strip()

        if chat_id not in user_data:
            bot.send_message(chat_id, "⛔ من فضلك، أرسل /start الأول.")
            return

        if 'stream_key' not in user_data[chat_id]:
            if len(text) > 10:
                user_data[chat_id]['stream_key'] = text
                bot.send_message(chat_id, "✅ تم حفظ *Stream Key*\nدابا سيفط رابط M3U8 للبث.", parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "⛔ Stream Key غير صحيح.")
            return

        if 'm3u8' not in user_data[chat_id]:
            if text.startswith("http") and text.endswith(".m3u8"):
                user_data[chat_id]['m3u8'] = text
                bot.send_message(chat_id, "🚀 كنوجد البث...")
                start_stream(chat_id)
            else:
                bot.send_message(chat_id, "⛔ رابط M3U8 غير صالح.")
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
            bot.send_message(chat_id, "✅ البث بدا مباشرة على Facebook Live!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ خطأ أثناء البث: {str(e)}")

    bot.polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))