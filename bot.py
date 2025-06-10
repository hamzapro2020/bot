import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import asyncio

# إعدادات
TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"

STREAM_NAME, M3U8_LINK, FB_KEYS = range(3)
processes = {}
rotating_keys = {}

# وظائف عامة
def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def monitor_stream(tag, cmd):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc
    proc.wait()
    processes.pop(tag, None)

async def rotate_keys(tag, m3u8_link, keys):
    idx = 0
    while tag in rotating_keys:
        key = keys[idx % len(keys)]
        rtmp_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
        print(f"Switching key for {tag}: {key}")

        # إعادة تشغيل ffmpeg مع المفتاح الجديد
        if tag in processes:
            proc = processes[tag]
            proc.terminate()
            try:
                proc.wait(timeout=1)  # انتظار إيقاف العملية الحالية
            except subprocess.TimeoutExpired:
                proc.kill()

        cmd = [
            "ffmpeg", "-re", "-i", m3u8_link,
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            rtmp_url,
        ]
        process = subprocess.Popen(cmd)
        processes[tag] = process

        idx += 1
        await asyncio.sleep(600)  # تبديل المفتاح كل 10 دقائق

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        "🎥 مرحباً! اختر من القائمة:\n\n"
        "🎬 تجهيز البث\n"
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
    )
    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard)

async def start_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل قائمة المفاتيح (مفتاح لكل سطر):")
    return FB_KEYS

async def get_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys = update.message.text.strip().splitlines()
    if not all(key.startswith("FB-") for key in keys):
        await update.message.reply_text("❌ بعض المفاتيح غير صالحة.")
        return ConversationHandler.END

    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    user_id = str(update.effective_user.id)
    tag = f"{user_id}_{name}"

    rotating_keys[tag] = keys
    asyncio.create_task(rotate_keys(tag, link, keys))
    await update.message.reply_text(f"✅ تم بدء البث!\n📛 الاسم: {name}")

    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tags = [tag for tag in processes if tag.startswith(user_id)]
    stopped = 0
    for tag in tags:
        if tag in rotating_keys:
            rotating_keys.pop(tag)
        if tag in processes:
            proc = processes[tag]
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
            processes.pop(tag, None)
            stopped += 1
    await update.message.reply_text(f"⏹ تم إيقاف {stopped} بث(ات)." if stopped else "❌ لا يوجد بث نشط.")

# إعداد البوت
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), start_prepare)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_keys)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, stop_stream))

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()