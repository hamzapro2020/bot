import json
import os
import subprocess
import threading
import time
import requests
from datetime import datetime, timedelta
from functools import wraps
import uuid

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# ===== إعدادات البوت =====
TOKEN = os.getenv("BOT_TOKEN")  # توكن البوت من متغير بيئة
ADMINS = [6444681745]  # استبدل بـ ID الأدمن

# ===== ملفات البيانات =====
os.makedirs("data", exist_ok=True)
USERS_FILE = "data/users.json"

# ===== أدوات مساعدة =====
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

# ===== تحقق اشتراك بريميوم =====
def premium_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        users = load_json(USERS_FILE)
        user = users.get(user_id, {})
        expires = user.get("expires")
        now = datetime.now()
        context.user_data["is_premium"] = bool(expires and datetime.fromisoformat(expires) > now)
        return await func(update, context)
    return wrapper

def can_stream(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    last = user.get("last_stream")
    premium = user.get("expires") and datetime.fromisoformat(user["expires"]) > datetime.now()
    if premium:
        return True, ""
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(hours=24):
            remaining = timedelta(hours=24) - elapsed
            return False, f"⏳ جرب لاحقًا بعد: {str(remaining).split('.')[0]}"
    return True, ""

def can_use_api_stream(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()

    expires = user.get("expires")
    if expires and datetime.fromisoformat(expires) > now:
        return True, None

    last_api = user.get("last_api_stream")
    if last_api:
        elapsed = now - datetime.fromisoformat(last_api)
        if elapsed < timedelta(hours=24):
            remaining = timedelta(hours=24) - elapsed
            return False, f"⏳ يمكنك استخدام API بعد: {str(remaining).split('.')[0]}"
    
    return True, None

# ===== واجهة الاستخدام =====
keyboard = ReplyKeyboardMarkup(
    [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "🧩 تجهيز البث API"]],
    resize_keyboard=True
)

# ===== إدارة الاشتراكات =====
async def add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ الأمر للأدمن فقط.")
    
    try:
        user_id = context.args[0]
        days = int(context.args[1])
        users = load_json(USERS_FILE)
        now = datetime.now()
        expires = now + timedelta(days=days)
        users[user_id] = users.get(user_id, {})
        users[user_id]["expires"] = expires.isoformat()
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم إعطاء اشتراك {days} يوم للمستخدم {user_id}.")
    except Exception as e:
        await update.message.reply_text("❌ الصيغة: /add_premium user_id عدد_الأيام")

async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ الأمر للأدمن فقط.")
    
    try:
        user_id = context.args[0]
        users = load_json(USERS_FILE)
        if user_id in users:
            users[user_id]["expires"] = None
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.")
        else:
            await update.message.reply_text("❌ المستخدم غير موجود.")
    except:
        await update.message.reply_text("❌ الصيغة: /remove_premium user_id")

# ===== تشغيل ffmpeg مع مراقبة =====
processes = {}

def monitor_stream(tag, cmd, retries=3):
    for attempt in range(retries):
        proc = subprocess.Popen(cmd)
        processes[tag] = proc
        proc.wait()
        time.sleep(5)
    print(f"[⛔] توقف البث {tag} بعد {retries} محاولات.")

# ===== واجهة محادثة للبث =====
STREAM_NAME, M3U8_LINK, FB_KEY, API_M3U8, API_TOKEN = range(5)

@premium_only
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
    await update.message.reply_text("🔑 أرسل مفتاح البث (FB-):")
    return FB_KEY

async def get_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    if not key.startswith("FB-"):
        await update.message.reply_text("❌ المفتاح غير صالح.")
        return ConversationHandler.END

    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]
    user_id = str(update.effective_user.id)
    is_premium = context.user_data.get("is_premium", False)

    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    vf = f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{name}':fontcolor=white:fontsize=24:x=10:y=h-th-10"
    if not is_premium:
        vf = f"scale='trunc(iw*360/ih/2)*2:360',{vf}"

    cmd = ["ffmpeg", "-re", "-i", link, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-f", "flv", output]
    tag = f"{user_id}_{name}"
    threading.Thread(target=monitor_stream, args=(tag, cmd)).start()

    users = load_json(USERS_FILE)
    users[user_id] = users.get(user_id, {})
    users[user_id]["last_stream"] = datetime.now().isoformat()
    users[user_id]["last_stream_info"] = {"name": name, "m3u8": link, "key": key}
    save_json(USERS_FILE, users)

    await update.message.reply_text("✅ تم بدء البث!")
    return ConversationHandler.END

# ===== API بث =====
async def start_api_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_use_api_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return API_M3U8

async def get_api_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["m3u8"] = update.message.text.strip()
    await update.message.reply_text("🔐 أرسل توكن Facebook:")
    return API_TOKEN

async def get_api_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    m3u8 = context.user_data["m3u8"]
    user_id = str(update.effective_user.id)

    res = requests.post(
        "https://graph.facebook.com/v19.0/me/live_videos",
        params={"access_token": token},
        data={"title": "بث مباشر", "status": "LIVE_NOW"}
    )

    if res.status_code != 200 or "stream_url" not in res.json():
        await update.message.reply_text("❌ فشل في الحصول على stream_url.")
        return ConversationHandler.END

    stream_url = res.json()["stream_url"]
    tag = f"api_{user_id}_{uuid.uuid4().hex[:6]}"
    cmd = [
        "ffmpeg", "-re", "-i", m3u8,
        "-vf", "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='API_Stream':fontcolor=white:fontsize=24:x=10:y=h-th-10",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-f", "flv", stream_url
    ]
    threading.Thread(target=monitor_stream, args=(tag, cmd)).start()

    users = load_json(USERS_FILE)
    users[user_id] = users.get(user_id, {})
    users[user_id]["last_api_stream"] = datetime.now().isoformat()
    save_json(USERS_FILE, users)

    await update.message.reply_text("✅ تم البث عبر API!")
    return ConversationHandler.END

# ===== أوامر أخرى =====
async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tags = [tag for tag in processes if tag.startswith(user_id)]
    for tag in tags:
        proc = processes.get(tag)
        if proc and proc.poll() is None:
            proc.terminate()
    await update.message.reply_text("⏹ تم إيقاف البث.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    info = users.get(user_id, {}).get("last_stream_info")
    if not info:
        return await update.message.reply_text("❌ لا يوجد بث لإعادة تشغيله.")
    
    name, link, key = info["name"], info["m3u8"], info["key"]
    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    vf = f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{name}':fontcolor=white:fontsize=24:x=10:y=h-th-10"
    vf = f"scale='trunc(iw*360/ih/2)*2:360',{vf}"
    cmd = ["ffmpeg", "-re", "-i", link, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-f", "flv", output]
    tag = f"{user_id}_{name}"
    threading.Thread(target=monitor_stream, args=(tag, cmd)).start()
    await update.message.reply_text(f"🔁 تمت إعادة التشغيل: {name}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 مرحبًا بك في بوت البث.", reply_markup=keyboard)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 تم الإلغاء.")
    return ConversationHandler.END

def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(🎬 تجهيز البث)$"), start_prepare),
                      MessageHandler(filters.Regex("^(🧩 تجهيز البث API)$"), start_api_prepare)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
            API_M3U8: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_m3u8)],
            API_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_token)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_premium", add_premium))
    application.add_handler(CommandHandler("remove_premium", remove_premium))
    application.add_handler(CommandHandler("stop", stop_stream))
    application.add_handler(CommandHandler("restart", restart_stream))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()

    # اضفنا حلقة انتظار في نهاية السكريبت ليبقى شغال دائمًا
    while True:
        time.sleep(10)
