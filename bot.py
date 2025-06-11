import os
import json
import threading
import subprocess
from datetime import datetime
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
import random
import string

TOKEN = os.getenv("TOKEN")  # ضع توكن بوت تيليجرام في متغير البيئة TOKEN
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
ADMIN_CHAT_ID = -1001234567890

os.makedirs("data", exist_ok=True)

STREAM_NAME, M3U8_LINK, FB_KEY, IG_M3U8_LINK = range(4)
processes = {}

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_admin(user_id):
    return user_id in ADMINS

def is_subscribed(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    expires = user.get("expires")
    if not expires:
        return False
    try:
        return datetime.fromisoformat(expires) > datetime.now()
    except:
        return False

def can_stream(user_id):
    if is_subscribed(user_id):
        return True, ""
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    usage = user.get("daily_stream_count", 0)
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    now = datetime.now()
    if not last_date or last_date.date() < now.date():
        usage = 0
    if usage >= 1:
        return False, "❌ وصلت للحد المجاني اليومي، اشترك للبث أكثر."
    return True, ""

def increment_daily_stream_count(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    if not last_date or last_date.date() < now.date():
        user["daily_stream_count"] = 1
        user["daily_stream_date"] = now.isoformat()
    else:
        user["daily_stream_count"] = user.get("daily_stream_count", 0) + 1
    users[str(user_id)] = user
    save_json(USERS_FILE, users)

def monitor_stream(tag, cmd):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc
    proc.wait()
    processes.pop(tag, None)

def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(tag, None)

def generate_random_key(length=24):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or "لا يوجد"
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"

    text = (
        f"مرحباً!\n"
        f"معرفك: `{user.id}`\n"
        f"اسم المستخدم: @{username}\n"
        f"الاسم: {full_name}\n"
        f"الحالة: {status}\n\n"
        f"اختر من القائمة:\n\n"
        "🎬 تجهيز البث\n"
        "🎬 تجهيز البث IG\n"
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
        "📥 تحميل ملف IPTV"
    )

    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز البث", "🎬 تجهيز البث IG", "⏹ إيقاف البث"],
         ["🔁 إعادة تشغيل البث", "📥 تحميل ملف IPTV"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

# تجهيز بث عادي

async def start_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
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
    await update.message.reply_text("🔑 أرسل مفتاح البث (يبدأ بـ FB-):")
    return FB_KEY

async def get_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    if not key.startswith("FB-"):
        await update.message.reply_text("❌ مفتاح غير صالح.")
        return ConversationHandler.END

    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"

    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=854:480",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]

    tag = f"{user_id}_{name}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    user["last_stream"] = datetime.now().isoformat()
    user["last_stream_info"] = {"m3u8": link, "key": key, "name": name}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء البث!\n📛 الاسم: {name}")

    return ConversationHandler.END

# تجهيز بث انستغرام

async def start_prepare_ig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    await update.message.reply_text("🔗 أرسل رابط m3u8 للبث IG:")
    return IG_M3U8_LINK

async def get_ig_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END

    # توليد مفتاح عشوائي للبث IG
    random_key = generate_random_key()
    output = f"rtmps://edgetee-upload-fra3-2.xx.fbcdn.net:443/rtmp/18175307881336019?s_bl=1&s_fbp=ams2-1&s_ow=10&s_prp=fra3-2&s_sw=0&s_tids=1&s_vt=ig&a={random_key}"

    user_id = str(update.effective_user.id)
    tag = f"{user_id}_ig_stream"

    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=854:480",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    user["last_stream"] = datetime.now().isoformat()
    user["last_stream_info"] = {"m3u8": link, "key": random_key, "name": "IG Stream"}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء بث انستغرام!\n🔑 المفتاح: {random_key}")

    return ConversationHandler.END

# إيقاف البث

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    last_stream = user.get("last_stream_info")
    if not last_stream:
        await update.message.reply_text("❌ لا يوجد بث جاري.")
        return

    tag = f"{user_id}_{last_stream.get('name', '')}".replace(" ", "_")
    stop_stream_process(tag)
    await update.message.reply_text("⏹ تم إيقاف البث.")

# إضافة مشترك (مثال)

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ أنت لست المسؤول.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("❌ استخدم: /adduser <user_id> <عدد الأيام>")
        return
    user_id = context.args[0]
    days = int(context.args[1])
    users = load_json(USERS_FILE)
    expires = datetime.now() + timedelta(days=days)
    users[user_id] = {"expires": expires.isoformat()}
    save_json(USERS_FILE, users)
    await update.message.reply_text(f"✅ تم إضافة المستخدم {user_id} لمدة {days} يوم.")

# حذف مشترك (مثال)

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ أنت لست المسؤول.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❌ استخدم: /removeuser <user_id>")
        return
    user_id = context.args[0]
    users = load_json(USERS_FILE)
    if user_id in users:
        users.pop(user_id)
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم حذف المستخدم {user_id}.")
    else:
        await update.message.reply_text("❌ المستخدم غير موجود.")

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    prepare_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), start_prepare)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
        },
        fallbacks=[],
    )

    prepare_ig_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث IG$"), start_prepare_ig)],
        states={
            IG_M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ig_m3u8)],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(prepare_conv)
    application.add_handler(prepare_ig_conv)
    application.add_handler(MessageHandler(filters.Regex("^⏹ إيقاف البث$"), stop_stream))
    application.add_handler(CommandHandler("adduser", add_user))
    application.add_handler(CommandHandler("removeuser", remove_user))

    application.run_polling()

if __name__ == "__main__":
    main()