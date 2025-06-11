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
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import asyncio
import requests
import re

# إعدادات
TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
IPTV_URL = "https://raw.githubusercontent.com/hamzapro2020/Iptv/refs/heads/main/stream.html"
ADMIN_CHAT_ID = -1001234567890

os.makedirs("data", exist_ok=True)

STREAM_NAME, M3U8_LINK, FB_KEY, IG_KEY = range(4)
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

# أوامر البوت

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
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
        "📥 تحميل ملف IPTV"
    )

    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "📥 تحميل ملف IPTV"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def show_stream_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("📘 تجهيز البث FB", callback_data="prepare_fb")],
        [InlineKeyboardButton("📸 تجهيز البث IG", callback_data="prepare_ig")],
    ]
    await update.message.reply_text("🔽 اختر نوع البث:", reply_markup=InlineKeyboardMarkup(buttons))

async def prepare_fb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await start_prepare(update, context)

async def prepare_ig_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_ig_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    output = key  # IG uses direct stream URL/key

    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4000k", "-maxrate", "4500k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=640:360",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "500k", "-maxrate", "600k", "-bufsize", "700k",
            "-c:a", "aac", "-b:a", "96k",
            "-f", "flv", output
        ]

    tag = f"{user_id}_{name}_IG"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

    await update.message.reply_text(f"✅ تم بدء بث Instagram\n📛 الاسم: {name}")
    return ConversationHandler.END

# ... جميع الدوال السابقة تبقى كما هي (start_prepare, get_stream_name, get_m3u8, get_fb_key, stop_stream، إلخ)

# تعديل handle_message لإظهار قائمة FB / IG
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز البث":
        return await show_stream_options(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "📥 تحميل ملف IPTV":
        return await download_and_send_iptv(update, context)
    else:
        await update.message.reply_text("❓ الرجاء اختيار خيار من القائمة.")

# main

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler_fb = ConversationHandler(
        entry_points=[CallbackQueryHandler(prepare_fb_callback, pattern="^prepare_fb$")],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    conv_handler_ig = ConversationHandler(
        entry_points=[CallbackQueryHandler(prepare_ig_callback, pattern="^prepare_ig$")],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            IG_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ig_key)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_subscriber))
    application.add_handler(CommandHandler("remove", remove_subscriber))
    application.add_handler(conv_handler_fb)
    application.add_handler(conv_handler_ig)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
