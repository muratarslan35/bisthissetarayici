import os
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode



# ======================================================
# ENV
# ======================================================

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

DB_PATH = "system.db"

# ======================================================
# DB
# ======================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ======================================================
# /START
# ======================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE telegram_chat_id=?", (chat_id,))
    existing = cur.fetchone()

    if existing:
        await update.message.reply_text(
            "✅ Telegram hesabınız zaten sisteme bağlı."
        )
        conn.close()
        return

    conn.close()

    context.user_data["awaiting_username"] = True

    await update.message.reply_text(
        "👤 Lütfen dashboard kullanıcı adınızı yazınız:"
    )

# ======================================================
# USERNAME BAĞLAMA
# ======================================================

async def link_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_username"):
        return

    username = update.message.text.strip()
    chat_id = str(update.effective_chat.id)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cur.fetchone()

    if not user:
        await update.message.reply_text(
            "❌ Böyle bir dashboard kullanıcı adı bulunamadı."
        )
        conn.close()
        return

    if user["telegram_chat_id"]:
        await update.message.reply_text(
            "⚠️ Bu hesap zaten başka bir Telegram hesabına bağlı."
        )
        conn.close()
        return

    cur.execute("""
        UPDATE users
        SET telegram_chat_id=?
        WHERE username=?
    """, (chat_id, username))

    conn.commit()
    conn.close()

    context.user_data["awaiting_username"] = False

    await update.message.reply_text(
        "✅ Telegram hesabınız başarıyla bağlandı.\n\n"
        "Ödeme onaylandığında kanal davetiniz gönderilecektir."
    )

# ======================================================
# INVITE GÖNDERME
# ======================================================

async def send_invite(context: ContextTypes.DEFAULT_TYPE):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, telegram_chat_id, subscription_end
        FROM users
        WHERE is_active=1
        AND status='approved'
        AND invite_sent=0
        AND telegram_chat_id IS NOT NULL
        AND subscription_end IS NOT NULL
    """)

    users = cur.fetchall()

    for user in users:
        try:
            expire_dt = datetime.strptime(
                user["subscription_end"],
                "%Y-%m-%d %H:%M:%S"
            )

            if expire_dt < datetime.now():
                continue

            expire_timestamp = int(expire_dt.timestamp())

            link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=expire_timestamp
            )

            await context.bot.send_message(
                chat_id=user["telegram_chat_id"],
                text=(
                    "🎉 <b>Ödeme Onaylandı</b>\n\n"
                    "Özel kanal giriş linkiniz:\n"
                    f"{link.invite_link}"
                ),
                parse_mode=ParseMode.HTML
            )

            cur.execute("""
                UPDATE users
                SET invite_sent=1,
                    invite_link=?
                WHERE id=?
            """, (link.invite_link, user["id"]))

            conn.commit()

        except Exception as e:
            print("Invite error:", e)

    conn.close()

# ======================================================
# ABONELİK KONTROL
# ======================================================

async def subscription_checker(context: ContextTypes.DEFAULT_TYPE):
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.now()

    cur.execute("""
        SELECT id, telegram_chat_id, subscription_end, expiry_warning_sent
        FROM users
        WHERE is_active=1
        AND telegram_chat_id IS NOT NULL
        AND subscription_end IS NOT NULL
    """)

    users = cur.fetchall()

    for user in users:
        try:
            end = datetime.strptime(
                user["subscription_end"],
                "%Y-%m-%d %H:%M:%S"
            )
            remaining = end - now

            # 🔔 24 saat kala uyarı
            if timedelta(hours=0) < remaining <= timedelta(days=1) and user["expiry_warning_sent"] == 0:
                await context.bot.send_message(
                    chat_id=user["telegram_chat_id"],
                    text=(
                        "⚠️ <b>Aboneliğinizin bitmesine 24 saatten az kaldı.</b>\n\n"
                        "Devam etmek için yenileme yapmayı unutmayın."
                    ),
                    parse_mode=ParseMode.HTML
                )

                cur.execute("""
                    UPDATE users
                    SET expiry_warning_sent=1
                    WHERE id=?
                """, (user["id"],))
                conn.commit()

            if end < now:
                await context.bot.ban_chat_member(
                    chat_id=CHANNEL_ID,
                    user_id=user["telegram_chat_id"]
                )

                await context.bot.unban_chat_member(
                    chat_id=CHANNEL_ID,
                    user_id=user["telegram_chat_id"]
                )

                cur.execute("""
                    UPDATE users
                    SET is_active=0,
                        status='expired',
                        invite_sent=0,
                        expiry_warning_sent=0
                    WHERE id=?
                """, (user["id"],))

                conn.commit()

        except Exception as e:
            print("Subscription check error:", e)

    conn.close()

# ======================================================
# MAIN (FIXED)
# ======================================================

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_username))

    app.job_queue.run_repeating(send_invite, interval=15, first=10)
    app.job_queue.run_repeating(subscription_checker, interval=3600, first=20)

    print("🤖 Bot aktif...")
    app.run_polling()

if __name__ == "__main__":
    main()
