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

# إعدادات
TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
IPTV_URL = "https://raw.githubusercontent.com/hamzapro2020/Iptv/refs/heads/main/stream.html"
ADMIN_CHAT_ID = -1001234567890

os.makedirs("data", exist_ok=True)

# حالات المحادثة
STREAM_NAME, M3U8_LINK, FB_KEY = range(3)
IG_STREAM_NAME, IG_M3U8_LINK, IG_KEY = range(3, 6)

# حفظ العمليات الجارية للبث
processes = {}

# دوال تحميل وحفظ JSON
def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# التحقق من الصلاحيات والاشتراك
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

# مراقبة البث وتشغيل ffmpeg
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

# معالجة محتوى IPTV
def process_iptv_content(content):
    content = re.sub(r'(video.xx.fbcdn.net)', r'iptv@\1', content)
    content = re.sub(r"{ *'title' *: *", "", content)
    content = re.sub(r'https?://[^\s]*(?:image|scontent)[^\s]*', '🎄', content)
    content = content.replace(";", "")
    content = content.replace("image", "By @rio3829")
    content = re.sub(r'}', '     \n\n\n', content)
    content = content.replace("}, {'title':", "Channel")
    content = content.replace("'", " ")
    content = re.sub(r'(https)', r'server ➡️ \1', content)
    return content

# --- أوامر البوت ---

# /start
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

# بدء تجهيز البث FB أو IG
async def start_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup(
        [["📺 تجهيز بث FB", "📸 تجهيز بث IG"]],
        resize_keyboard=True,
    )
    await update.message.reply_text("🔍 اختر نوع البث:", reply_markup=keyboard)
    return ConversationHandler.END

# --- بث إنستغرام ---

async def start_ig_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    await update.message.reply_text("📛 أرسل اسم البث لإنستغرام:")
    return IG_STREAM_NAME

async def get_ig_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return IG_M3U8_LINK

async def get_ig_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث لإنستغرام:")
    return IG_KEY

async def get_ig_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"

    cmd = [
        "ffmpeg", "-re", "-i", link,
        "-vf", "scale=720:1280",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "4000k",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "flv", "-rtbufsize", "1000M",
        output
    ]
    tag = f"{user_id}_{name}_IG"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    await update.message.reply_text(f"✅ تم بدء بث إنستغرام!")
    return ConversationHandler.END

# --- بث فيسبوك ---

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    await update.message.reply_text("📛 أرسل اسم البث لفيسبوك:")
    return STREAM_NAME

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث لفيسبوك:")
    return FB_KEY

async def get_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    output = f"rtmp://live-api-s.facebook.com:80/rtmp/{key}"

    cmd = [
        "ffmpeg", "-re", "-i", link,
        "-vf", "scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "3000k", "-maxrate", "3500k", "-bufsize", "5000k",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "flv", "-rtbufsize", "1000M",
        output
    ]
    tag = f"{user_id}_{name}_FB"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()
    increment_daily_stream_count(update.effective_user.id)

    await update.message.reply_text(f"✅ تم بدء بث فيسبوك!")
    return ConversationHandler.END

# إيقاف البث
async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stopped = False
    for tag in list(processes.keys()):
        if tag.startswith(user_id):
            stop_stream_process(tag)
            stopped = True
    if stopped:
        await update.message.reply_text("⏹ تم إيقاف البث.")
    else:
        await update.message.reply_text("❌ لا يوجد بث جاري لإيقافه.")

# إعادة تشغيل البث (ببساطة نوقفه ثم نعيد تشغيله بنفس البيانات)
async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stopped = False
    for tag in list(processes.keys()):
        if tag.startswith(user_id):
            stop_stream_process(tag)
            stopped = True
    if not stopped:
        await update.message.reply_text("❌ لا يوجد بث جاري لإعادة تشغيله.")
        return

    # هنا يمكنك إضافة إعادة تشغيل بناءً على بيانات محفوظة (مفقودة في السكربت الحالي)
    await update.message.reply_text("🔄 تم إعادة تشغيل البث (لكن الوظيفة تحتاج لإكمال).")

# تحميل وإرسال ملف IPTV
async def download_and_send_iptv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = requests.get(IPTV_URL)
        response.raise_for_status()
        content = process_iptv_content(response.text)
        await update.message.reply_text(f"📥 ملف IPTV:\n\n{content}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في تحميل ملف IPTV:\n{e}")

# معالجة الرسائل النصية
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز البث":
        return await start_prepare(update, context)
    elif text == "📺 تجهيز بث FB":
        return await get_stream_name(update, context)
    elif text == "📸 تجهيز بث IG":
        return await start_ig_stream(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "📥 تحميل ملف IPTV":
        return await download_and_send_iptv(update, context)
    else:
        await update.message.reply_text("❓ الرجاء اختيار خيار من القائمة.")

# إدارة المشتركين (إضافة وحذف) - تحتاج تنفيذ فعلي حسب قاعدة بياناتك

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ ليس لديك صلاحية.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❌ استخدم: /add <user_id>")
        return
    target_id = context.args[0]
    users = load_json(USERS_FILE)
    users[target_id] = {
        "expires": (datetime.now() + timedelta(days=30)).isoformat()
    }
    save_json(USERS_FILE, users)
    await update.message.reply_text(f"✅ تمت إضافة المشترك {target_id} لمدة 30 يوم.")

async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ ليس لديك صلاحية.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❌ استخدم: /remove <user_id>")
        return
    target_id = context.args[0]
    users = load_json(USERS_FILE)
    if target_id in users:
        users.pop(target_id)
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم حذف المشترك {target_id}.")
    else:
        await update.message.reply_text("❌ هذا المستخدم غير موجود.")

# --- main ---

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    fb_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📺 تجهيز بث FB$"), get_stream_name)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    ig_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📸 تجهيز بث IG$"), start_ig_stream)],
        states={
            IG_STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ig_stream_name)],
            IG_M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ig_m3u8)],
            IG_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ig_key)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_subscriber))
    application.add_handler(CommandHandler("remove", remove_subscriber))
    application.add_handler(fb_conv)
    application.add_handler(ig_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()