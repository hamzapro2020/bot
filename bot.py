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

STREAM_NAME, STREAM_URL, STREAM_KEY = range(3)
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
        "🎬 تجهيز بث إنستغرام\n"
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
        "📥 تحميل ملف IPTV"
    )

    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز بث إنستغرام", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "📥 تحميل ملف IPTV"]],
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
    await update.message.reply_text("🔗 أرسل رابط بث إنستغرام (URL يبدأ بـ rtmps://):")
    return STREAM_URL

async def get_stream_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("rtmps://"):
        await update.message.reply_text("❌ رابط غير صالح، يجب أن يبدأ بـ rtmps://")
        return ConversationHandler.END
    context.user_data["stream_url"] = url
    await update.message.reply_text("🔑 أرسل مفتاح البث (Stream Key):")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    url = context.user_data["stream_url"]

    output = f"{url}/{key}"

    if is_subscribed(update.effective_user.id):
        # جودة عالية للمشتركين
        cmd = [
            "ffmpeg", "-re", "-i", "pipe:0",
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]
        # لإعادة توجيه من m3u8 إلى ffmpeg pipe:0 يمكن إضافة لاحقاً لو عندك مصدر
    else:
        # جودة منخفضة لغير المشتركين
        cmd = [
            "ffmpeg", "-re", "-i", "pipe:0",
            "-vf", "scale=640:360",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "800k", "-maxrate", "1000k", "-bufsize", "1200k",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]

    # ملاحظة: هنا عليك تعديل إذا كان المصدر من ملف أو من رابط مباشر
    # لتبسيط السكربت سنعتبر أن الرابط المرسل هو الرابط الكامل للبث

    # سنستخدم الرابط مباشرة كمدخل
    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", context.user_data["stream_url"],
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", context.user_data["stream_url"],
            "-vf", "scale=640:360",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "800k", "-maxrate", "1000k", "-bufsize", "1200k",
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
    user["last_stream_info"] = {"url": url, "key": key, "name": name}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء البث!\n📛 الاسم: {name}")

    if not is_subscribed(update.effective_user.id):
        def stop_and_notify():
            stop_stream_process(tag)
            asyncio.run_coroutine_threadsafe(
                update.message.reply_text(
                    "⏰ انتهى وقت البث المجاني (30 دقيقة). يرجى الاشتراك لمواصلة البث."
                ),
                context.application.loop
            )
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"📢 المستخدم @{update.effective_user.username or update.effective_user.id} انتهى بثه المجاني."
                ),
                context.application.loop
            )

        timer = threading.Timer(1800, stop_and_notify)
        timer.daemon = True
        timer.start()

    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tags = [tag for tag in processes if tag.startswith(user_id)]
    stopped = 0
    for tag in tags:
        stop_stream_process(tag)
        stopped += 1
    await update.message.reply_text(f"⏹ تم إيقاف {stopped} بث(ات)." if stopped else "❌ لا يوجد بث نشط.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id)
    if not user or "last_stream_info" not in user:
        await update.message.reply_text("❌ لا يوجد بث سابق لإعادة تشغيله.")
        return
    context.user_data.update(user["last_stream_info"])
    return await get_stream_key(update, context)

async def download_and_send_iptv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id)
    expires = user.get("expires") if user else None
    if not (expires and datetime.fromisoformat(expires) > datetime.now()):
        await update.message.reply_text("❌ الملف متاح فقط للمشتركين.\n🔑 يرجى الاشتراك للحصول على الملف.")
        return
    await update.message.reply_text("⬇️ جاري تحميل ومعالجة ملف IPTV...")
    try:
        response = requests.get(IPTV_URL)
        response.raise_for_status()
        content = response.text
        processed_content = process_iptv_content(content)
    except Exception as e:
        await update.message.reply_text(f"❌ فشل التحميل أو المعالجة: {e}")
        return
    filename = f"IPTV_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(processed_content)
    with open(filename, "rb") as file:
        await update.message.reply_document(file)
    os.remove(filename)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز بث إنستغرام":
        return await start_prepare(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "📥 تحميل ملف IPTV":
        return await download_and_send_iptv(update, context)
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
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز بث إنستغرام$"), start_prepare)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            STREAM_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_url)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_handler(CommandHandler("add", add_subscriber))
    application.add_handler(CommandHandler("remove", remove_subscriber))
    application.add_handler(CommandHandler("stop", stop_stream))
    application.add_handler(CommandHandler("restart", restart_stream))

    application.run_polling()

if __name__ == "__main__":
    main()
