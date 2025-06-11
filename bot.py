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
import requests
import re
import random
import string

# إعدادات
TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
IPTV_URL = "https://raw.githubusercontent.com/hamzapro2020/Iptv/refs/heads/main/stream.html"
ADMIN_CHAT_ID = -1001234567890

os.makedirs("data", exist_ok=True)

STREAM_NAME, M3U8_LINK, FB_KEY = range(3)
IG_M3U8, IG_KEY = range(3, 5)
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
    return expires and datetime.fromisoformat(expires) > datetime.now()

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    users = load_json(USERS_FILE)
    user_data = users.get(str(user.id), {})

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
        "🔁 إعادة تشغيل البث"
    )

    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز البث", "🎬 تجهيز البث IG"], ["⏹ إيقاف البث", "🔁 إعادة تشغيل البث"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

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

    cmd = [
        "ffmpeg", "-re", "-i", link,
        "-vf", "scale=854:480" if not is_subscribed(update.effective_user.id) else "scale=1920:1080",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "1000k" if not is_subscribed(update.effective_user.id) else "4500k",
        "-maxrate", "1200k" if not is_subscribed(update.effective_user.id) else "5000k",
        "-bufsize", "1500k" if not is_subscribed(update.effective_user.id) else "6000k",
        "-c:a", "aac", "-b:a", "128k" if not is_subscribed(update.effective_user.id) else "160k",
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
    user["last_stream_info"] = {"m3u8": link, "key": key, "name": name, "type": "FB"}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء البث!
📛 الاسم: {name}")
    return ConversationHandler.END

async def get_ig_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("📛 جاري توليد معرف ومفتاح IG تلقائياً...")
    key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    stream_key = f"18175307881336019?s_bl=1&s_fbp=ams2-1&s_ow=10&s_prp=fra3-2&s_sw=0&s_tids=1&s_vt=ig&a={key}"
    context.user_data["key"] = stream_key

    user_id = str(update.effective_user.id)
    name = f"IG_{datetime.now().strftime('%H%M%S')}"
    link = context.user_data["m3u8"]
    output = f"rtmps://edgetee-upload-fra3-2.xx.fbcdn.net:443/rtmp/{stream_key}"

    tag = f"{user_id}_{name}"
    cmd = [
        "ffmpeg", "-re", "-i", link,
        "-vf", "scale=720:1280",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "1500k", "-maxrate", "1800k", "-bufsize", "2000k",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "flv", "-rtbufsize", "1500M",
        output
    ]

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    user["last_stream_info"] = {"m3u8": link, "key": stream_key, "name": name, "type": "IG"}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء بث Instagram
📛 الاسم: {name}")
    return ConversationHandler.END

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id)
    if not user or "last_stream_info" not in user:
        await update.message.reply_text("❌ لا يوجد بث سابق لإعادة تشغيله.")
        return

    info = user["last_stream_info"]
    context.user_data["stream_name"] = info.get("name", "NoName")
    context.user_data["m3u8"] = info["m3u8"]
    context.user_data["key"] = info["key"]
    stream_type = info.get("type", "FB")

    if stream_type == "IG":
        return await get_ig_m3u8(update, context)
    else:
        return await get_fb_key(update, context)

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tags = [tag for tag in processes if tag.startswith(user_id)]
    stopped = 0
    for tag in tags:
        stop_stream_process(tag)
        stopped += 1
    await update.message.reply_text(f"⏹ تم إيقاف {stopped} بث(ات)." if stopped else "❌ لا يوجد بث نشط.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز البث":
        return await start_prepare(update, context)
    elif text == "🎬 تجهيز البث IG":
        await update.message.reply_text("🔗 أرسل رابط M3U8 لبث Instagram:")
        return IG_M3U8
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    else:
        await update.message.reply_text("❓ الرجاء اختيار خيار من القائمة.")

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        user_id = context.args[0]
        days = int(context.args[1])
        users = load_json(USERS_FILE)
        expires = datetime.now() + timedelta(days=days)
        users[user_id] = users.get(user_id, {})
        users[user_id]["expires"] = expires.isoformat()
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم الاشتراك للمستخدم {user_id} لمدة {days} يوم.")
        try:
            await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك. استمتع بالخدمة!")
        except:
            pass
    except:
        await update.message.reply_text("❌ الاستخدام: /add <USER_ID> <DAYS>")

async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        user_id = context.args[0]
        users = load_json(USERS_FILE)
        if user_id in users:
            users[user_id].pop("expires", None)
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}")
        else:
            await update.message.reply_text("❌ المستخدم غير موجود.")
    except:
        await update.message.reply_text("❌ الاستخدام: /remove <USER_ID>")

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), start_prepare)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
            IG_M3U8: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ig_m3u8)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_subscriber))
    application.add_handler(CommandHandler("remove", remove_subscriber))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
