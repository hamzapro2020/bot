import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
import asyncio
import requests
import re

# الإعدادات
TOKEN = os.getenv("TOKEN") or "ضع_التوكن_هنا"
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
IPTV_URL = "https://raw.githubusercontent.com/hamzapro2020/Iptv/refs/heads/main/stream.html"
ADMIN_CHAT_ID = -1001234567890

os.makedirs("data", exist_ok=True)

# الحالات
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY = range(4)

processes = {}

# أدوات مساعدة
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
    return expires and datetime.fromisoformat(expires) > datetime.now()

def can_stream(user_id):
    if is_subscribed(user_id):
        return True, ""
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    usage = user.get("daily_stream_count", 0)
    last_date = datetime.fromisoformat(user.get("daily_stream_date", "1970-01-01T00:00:00"))
    if last_date.date() < datetime.now().date():
        usage = 0
    if usage >= 1:
        return False, "❌ وصلت للحد المجاني اليومي، اشترك للبث أكثر."
    return True, ""

def increment_daily_stream_count(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()
    last_date = datetime.fromisoformat(user.get("daily_stream_date", "1970-01-01T00:00:00"))
    if last_date.date() < now.date():
        user["daily_stream_count"] = 1
    else:
        user["daily_stream_count"] = user.get("daily_stream_count", 0) + 1
    user["daily_stream_date"] = now.isoformat()
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

def process_iptv_content(content):
    content = re.sub(r'(video\.xx\.fbcdn\.net)', r'iptv@\1', content)
    content = re.sub(r"\{ *'title' *: *", "", content)
    content = re.sub(r'https?://[^\s]*(?:image|scontent)[^\s]*', '🎄', content)
    content = content.replace(";", "")
    content = content.replace("image", "By @rio3829")
    content = re.sub(r'}', '     \n\n\n', content)
    content = content.replace("}, {'title':", "Channel")
    content = content.replace("'", " ")
    content = re.sub(r'(https)', r'server ➡️ \1', content)
    return content

# الأوامر

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"
    username = user.username or "لا يوجد"
    name = f"{user.first_name} {user.last_name or ''}".strip()

    text = (
        f"مرحباً {name}!\n"
        f"معرفك: `{user.id}`\n"
        f"اسم المستخدم: @{username}\n"
        f"الحالة: {status}\n\n"
        f"اختر من القائمة:\n\n"
        "🎬 تجهيز البث\n"
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
        "📥 تحميل ملف IPTV"
    )
    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "📥 تحميل ملف IPTV"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def start_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Live FB", callback_data="live_fb"),
            InlineKeyboardButton("Live IG", callback_data="live_ig")
        ]]
    )
    await update.message.reply_text("اختر نوع البث:", reply_markup=keyboard)
    return SELECT_BROADCAST_TYPE

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["broadcast_type"] = query.data
    await query.message.reply_text("🎥 أرسل اسم البث:")
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
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    key = update.message.text.strip()
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    typ = context.user_data["broadcast_type"]

    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}" if typ == "live_fb" else f"rtmps://live-upload.instagram.com:443/rtmp/{key}"

    cmd = [
        "ffmpeg", "-re", "-i", link,
        "-vf", "scale=854:480" if not is_subscribed(update.effective_user.id) else "scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "1000k", "-maxrate", "2500k", "-bufsize", "3000k",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-f", "flv", "-rtbufsize", "1500M", output
    ]

    tag = f"{user_id}_{name}_{typ}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

    users = load_json(USERS_FILE)
    users[user_id] = users.get(user_id, {})
    users[user_id]["last_stream"] = {
        "name": name, "link": link, "key": key, "broadcast_type": typ, "started_at": datetime.now().isoformat()
    }
    save_json(USERS_FILE, users)

    await update.message.reply_text("✅ تم بدء البث بنجاح!")

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = load_json(USERS_FILE).get(user_id, {})
    last = user.get("last_stream")
    if last:
        tag = f"{user_id}_{last['name']}_{last['broadcast_type']}"
        stop_stream_process(tag)
        await update.message.reply_text("⏹ تم إيقاف البث.")
    else:
        await update.message.reply_text("❌ لا يوجد بث لتوقيفه.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = load_json(USERS_FILE).get(user_id, {})
    last = user.get("last_stream")
    if not last:
        await update.message.reply_text("❌ لا يوجد بث لإعادة تشغيله.")
        return
    tag = f"{user_id}_{last['name']}_{last['broadcast_type']}"
    stop_stream_process(tag)
    context.user_data.update(last)
    await get_stream_key(update, context)

async def get_iptv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(IPTV_URL)
        await update.message.reply_text(process_iptv_content(r.text))
    except:
        await update.message.reply_text("❌ خطأ في تحميل ملف IPTV.")

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = context.args[0]
        days = int(context.args[1])
        users = load_json(USERS_FILE)
        users[uid] = users.get(uid, {})
        users[uid]["expires"] = (datetime.now() + timedelta(days=days)).isoformat()
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم الاشتراك للمستخدم {uid} لمدة {days} يوم.")
    except:
        await update.message.reply_text("❌ استخدم: /add <USER_ID> <DAYS>")

async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = context.args[0]
        users = load_json(USERS_FILE)
        if uid in users:
            users[uid].pop("expires", None)
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم إلغاء اشتراك المستخدم {uid}")
        else:
            await update.message.reply_text("❌ المستخدم غير موجود.")
    except:
        await update.message.reply_text("❌ استخدم: /remove <USER_ID>")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم إلغاء العملية.")
    return ConversationHandler.END

# تشغيل البوت
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_stream))
    app.add_handler(CommandHandler("restart", restart_stream))
    app.add_handler(CommandHandler("iptv", get_iptv))
    app.add_handler(CommandHandler("add", add_subscriber))
    app.add_handler(CommandHandler("remove", remove_subscriber))

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), start_prepare)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    app.run_polling()

if __name__ == "__main__":
    main()