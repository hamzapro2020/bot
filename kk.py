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
TOKEN = os.getenv("BOT_TOKEN")  # تأكد من تعيين متغير البيئة على Render
ADMINS = [8145101051]  # ضع هنا معرف الأدمن الخاص بك

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
            return False, f"⏳ جرب الاشتراك للميزات الكاملة: @premuimuser12 يمكنك البث بعد: {str(remaining).split('.')[0]}"
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
            return False, f"⏳ جرب الاشتراك للميزات الكاملة: @premuimuser12 يمكنك البث API بعد: {str(remaining).split('.')[0]}"
    return True, None

# ===== لوحة الأزرار =====
keyboard = ReplyKeyboardMarkup(
    [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "🧩 تجهيز البث API"]],
    resize_keyboard=True
)

# ===== بث =====
STREAM_NAME, M3U8_LINK, FB_KEY, API_M3U8, API_TOKEN = range(5)
processes = {}

def monitor_stream(tag, cmd, retries=3):
    for attempt in range(retries):
        proc = subprocess.Popen(cmd)
        processes[tag] = proc
        proc.wait()
        time.sleep(5)
    print(f"[⛔] توقف البث {tag} بعد {retries} محاولات.")

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
    is_premium = context.user_data.get("is_premium", False)
    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"

    vf_filter = (
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{name}':fontcolor=white:fontsize=24:x=10:y=h-th-10"
    )
    if not is_premium:
        vf_filter = f"scale='trunc(iw*360/ih/2)*2:360',{vf_filter}"

    cmd = [
        "ffmpeg", "-re", "-i", link, "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-f", "flv", output
    ]
    tag = f"{user_id}_{name}"

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    users = load_json(USERS_FILE)
    users[user_id] = users.get(user_id, {})
    users[user_id]["last_stream"] = datetime.now().isoformat()
    users[user_id]["last_stream_info"] = {"m3u8": link, "key": key, "name": name}
    save_json(USERS_FILE, users)

    await update.message.reply_text(
        f"✅ تم بدء البث!\n📛 الاسم: {name}\n👤 {'مشترك' if is_premium else 'مجاني'}"
    )
    return ConversationHandler.END

async def start_api_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_use_api_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    await update.message.reply_text("🔗 أرسل رابط M3U8 من API:")
    return API_M3U8

async def get_api_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔐 أرسل توكن Facebook:")
    return API_TOKEN

async def get_api_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    m3u8 = context.user_data["m3u8"]
    user_id = str(update.effective_user.id)

    response = requests.post(
        "https://graph.facebook.com/v19.0/me/live_videos",
        params={"access_token": token},
        data={"title": "بث مباشر عبر API", "status": "LIVE_NOW"}
    )

    if response.status_code != 200 or "stream_url" not in response.json():
        await update.message.reply_text("❌ فشل في إنشاء البث. تحقق من التوكن.")
        return ConversationHandler.END

    stream_url = response.json()["stream_url"]
    tag = f"api_{user_id}_{uuid.uuid4().hex[:6]}"
    cmd = [
        "ffmpeg", "-re", "-i", m3u8,
        "-vf", "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='API_Stream':fontcolor=white:fontsize=24:x=10:y=h-th-10",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-f", "flv", stream_url
    ]

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    users = load_json(USERS_FILE)
    users[user_id] = users.get(user_id, {})
    users[user_id]["last_api_stream"] = datetime.now().isoformat()
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء البث باستخدام API!")
    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tags = [tag for tag in processes if tag.startswith(user_id)]
    stopped = 0
    for tag in tags:
        proc = processes.get(tag)
        if proc and proc.poll() is None:
            proc.terminate()
            stopped += 1
    await update.message.reply_text(
        f"⏹ تم إيقاف {stopped} بث(ات)." if stopped else "❌ لا يوجد بث نشط."
    )

@premium_only
async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id)
    if not user or "last_stream_info" not in user:
        await update.message.reply_text("❌ لا يوجد بث سابق لإعادة تشغيله.")
        return

    info = user["last_stream_info"]
    name, link, key = info["name"], info["m3u8"], info["key"]
    is_premium = context.user_data.get("is_premium", False)
    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"

    vf_filter = (
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{name}':fontcolor=white:fontsize=24:x=10:y=h-th-10"
    )
    if not is_premium:
        vf_filter = f"scale='trunc(iw*360/ih/2)*2:360',{vf_filter}"

    cmd = [
        "ffmpeg", "-re", "-i", link, "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-f", "flv", output
    ]
    tag = f"{user_id}_{name}"

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    users[user_id]["last_stream"] = datetime.now().isoformat()
    save_json(USERS_FILE, users)

    await update.message.reply_text("✅ تم إعادة تشغيل البث.")

# ===== أوامر الأدمن =====
async def add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    try:
        target_id = context.args[0]
        users = load_json(USERS_FILE)
        users[target_id] = users.get(target_id, {})
        users[target_id]["expires"] = (datetime.now() + timedelta(days=30)).isoformat()
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم ترقية {target_id} إلى مشترك بريميوم.")
    except Exception:
        await update.message.reply_text("❌ فشل تنفيذ الأمر. استخدم: /add_premium <user_id>")

async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    try:
        target_id = context.args[0]
        users = load_json(USERS_FILE)
        if target_id in users and "expires" in users[target_id]:
            users[target_id].pop("expires")
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم إزالة اشتراك {target_id}.")
        else:
            await update.message.reply_text("⚠️ المستخدم ليس لديه اشتراك.")
    except Exception:
        await update.message.reply_text("❌ فشل تنفيذ الأمر. استخدم: /remove_premium <user_id>")

# ===== بدء البوت =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! استخدم الأزرار لتجهيز أو إيقاف البث.", reply_markup=keyboard)

def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), start_prepare)],
        states={
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
        },
        fallbacks=[]
    )

    api_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧩 تجهيز البث API$"), start_api_prepare)],
        states={
            API_M3U8: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_m3u8)],
            API_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_token)],
        },
        fallbacks=[]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_premium", add_premium))
    application.add_handler(CommandHandler("remove_premium", remove_premium))
    application.add_handler(conv_handler)
    application.add_handler(api_conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^⏹ إيقاف البث$"), stop_stream))
    application.add_handler(MessageHandler(filters.Regex("^🔁 إعادة تشغيل البث$"), restart_stream))

    print("✅ البوت يعمل على Render كعامل خلفي (Worker)...")
    application.run_polling()

if __name__ == "__main__":
    main()