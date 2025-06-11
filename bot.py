import os
import json
import threading
import subprocess
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)
import re

# إعدادات عامة
TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# مراحل الحوار
PLATFORM_CHOOSE, STREAM_NAME, M3U8_LINK, STREAM_KEY = range(4)

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

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📘 تجهيز بث Facebook", callback_data="stream_fb")],
            [InlineKeyboardButton("📸 تجهيز بث Instagram", callback_data="stream_ig")]
        ])
        await update.message.reply_text("🔰 اختر نوع البث:", reply_markup=keyboard)
        return PLATFORM_CHOOSE

    elif text == "⏹ إيقاف البث":
        # إيقاف البث الخاص بالمستخدم (إذا كان موجود)
        tag_prefix = str(user_id) + "_"
        stopped = False
        for tag in list(processes.keys()):
            if tag.startswith(tag_prefix):
                stop_stream_process(tag)
                stopped = True
        if stopped:
            await update.message.reply_text("✅ تم إيقاف البث.")
        else:
            await update.message.reply_text("❌ لا يوجد بث يعمل حالياً.")
        return ConversationHandler.END

    else:
        await update.message.reply_text("❌ الخيار غير معروف.")
        return ConversationHandler.END

async def handle_platform_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data
    if platform not in ("stream_fb", "stream_ig"):
        await query.edit_message_text("❌ خيار غير صالح.")
        return ConversationHandler.END
    if platform == "stream_fb":
        context.user_data["platform"] = "fb"
        await query.edit_message_text("🎥 أرسل اسم البث:")
    else:
        context.user_data["platform"] = "ig"
        await query.edit_message_text("🎥 أرسل اسم البث (كمعرف):")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح، يجب أن ينتهي بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    platform = context.user_data.get("platform", "fb")

    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]

    # بناء رابط الخروج حسب المنصة
    if platform == "fb":
        # هنا يمكنك تعديل بناء رابط Facebook حسب مفتاح البث الحقيقي
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    else:
        # رابط بث Instagram (تخميني، قد يحتاج تعديل حسب الخدمة الفعلية)
        output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"

    # إعداد أمر ffmpeg حسب الاشتراك
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

    # بدء ffmpeg في Thread جديد
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    # تحديث عداد البث المجاني
    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

    await update.message.reply_text(f"✅ بدأ البث لمنصة {platform.upper()} باسم '{name}'.\nيمكنك إيقافه عبر زر إيقاف البث.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), handle_menu)],
        states={
            PLATFORM_CHOOSE: [CallbackQueryHandler(handle_platform_choice)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    # التعامل مع باقي الأزرار في القائمة الرئيسية
    app.add_handler(MessageHandler(filters.Regex("^⏹ إيقاف البث$"), handle_menu))
    app.add_handler(MessageHandler(filters.Regex("^(🔁 إعادة تشغيل البث|📥 تحميل ملف IPTV)$"), handle_menu))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()