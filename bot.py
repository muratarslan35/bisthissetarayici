import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

# ======================================================
# ENV
# ======================================================

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")  # Flask ile aynı isim

DB_PATH = "system.db"

# ======================================================
# DB
# ======================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ======================================================
# START COMMAND
# ======================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username or f"user_{chat_id}"

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE telegram_chat_id=?", (chat_id,))
    existing = cur.fetchone()

    if existing:
        await update.message.reply_text(
            "ℹ️ Sistem zaten kayıtlı.\nÖdeme onayı bekleniyor olabilir."
        )
        conn.close()
        return

    cur.execute("""
        INSERT INTO users (
            username,
            password_hash,
            telegram_chat_id,
            is_active,
            status,
            invite_sent
        )
        VALUES (?, ?, ?, 0, 'pending', 0)
    """, (
        f"tg_{chat_id}",
        "telegram_only",
        chat_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Kayıt alındı.\n\n"
        "💳 Ödemeniz onaylandığında özel kanal davet linkiniz gönderilecektir."
    )

# ======================================================
# INVITE LINK GENERATION
# ======================================================

async def send_invite(context: ContextTypes.DEFAULT_TYPE):
    conn = get_connection()
    cur = conn.cursor()

    # SADECE approved ve aktif kullanıcılar
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

            # Eğer süresi geçmişse invite üretme
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
# SUBSCRIPTION CHECK
# ======================================================

async def subscription_checker(context: ContextTypes.DEFAULT_TYPE):
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()

    cur.execute("""
        SELECT id, telegram_chat_id, subscription_end, status
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

            # 1 Gün Kala Hatırlatma
            if user["status"] == "approved" and end.date() == tomorrow:
                await context.bot.send_message(
                    chat_id=user["telegram_chat_id"],
                    text="⚠️ Yarın aboneliğiniz sona eriyor."
                )

            # Süre Bitti → Kick + Status Güncelle
            if end < now and user["status"] == "approved":
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
                        invite_sent=0
                    WHERE id=?
                """, (user["id"],))

                conn.commit()

        except Exception as e:
            print("Subscription check error:", e)

    conn.close()

# ======================================================
# MAIN
# ======================================================

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.job_queue.run_repeating(send_invite, interval=15, first=10)
    app.job_queue.run_repeating(subscription_checker, interval=3600, first=20)

    print("🤖 Bot aktif...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
