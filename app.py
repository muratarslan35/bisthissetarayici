import os
import time
import threading
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4

from dotenv import load_dotenv
from flask import (
    Flask, jsonify, render_template,
    request, session, redirect
)
from werkzeug.security import generate_password_hash, check_password_hash

from database import init_db, get_connection

from fetch_bist import fetch_bist_data
from signal_engine import (
    process_symbol_signals,
    update_success_targets,
    format_signal_message,
    build_daily_success_report,
    build_weekly_success_report,
    reset_daily_success_if_needed,
    reset_weekly_success_if_needed,
)

from dashboard import (
    dashboard_bp,
    push_signal,
    push_success_signal
)

# ======================================================
# ENV
# ======================================================
load_dotenv()

# ======================================================
# TIME
# ======================================================
TR_TZ = ZoneInfo("Europe/Istanbul")
BIST_OPEN = dtime(9, 40)
BIST_CLOSE = dtime(18, 5)
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# ======================================================
# TELEGRAM
# ======================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# ======================================================
# FLASK
# ======================================================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key")
app.register_blueprint(dashboard_bp)

init_db()

# ======================================================
# HELPERS
# ======================================================

def now_tr():
    return datetime.now(TR_TZ)

def is_market_open(now=None):
    now = now or now_tr()
    if now.weekday() >= 5:
        return False
    return BIST_OPEN <= now.time() <= BIST_CLOSE

def subscription_valid(user_row):
    if not user_row or not user_row["subscription_end"]:
        return False
    try:
        end = datetime.strptime(user_row["subscription_end"], "%Y-%m-%d %H:%M:%S")
        return end > datetime.now()
    except:
        return False

def send_user_telegram(chat_id, text):
    if not TELEGRAM_TOKEN or not chat_id:
        return
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=5
        )
    except:
        pass

# ======================================================
# TELEGRAM CHANNEL CONTROL
# ======================================================

def create_invite_link():
    import requests
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/createChatInviteLink",
            json={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "member_limit": 1
            },
            timeout=5
        )
        data = res.json()
        if data.get("ok"):
            return data["result"]["invite_link"]
    except:
        pass
    return None


def kick_from_channel(chat_id):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/banChatMember",
            json={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "user_id": chat_id
            },
            timeout=5
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/unbanChatMember",
            json={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "user_id": chat_id
            },
            timeout=5
        )
    except:
        pass


def broadcast_signal(text):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT telegram_chat_id, subscription_end, status
        FROM users
        WHERE is_active=1
    """)
    users = cur.fetchall()

    for u in users:
        if u["status"] != "approved":
            continue
        if not subscription_valid(u):
            continue
        send_user_telegram(u["telegram_chat_id"], text)

    conn.close()

# ======================================================
# SESSION CONTROL (TEK CİHAZ)
# ======================================================

def register_session(username):
    sid = str(uuid4())
    session["sid"] = sid
    session["user"] = username

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET active_session_id=?, last_login_at=? WHERE username=?",
        (sid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username)
    )
    conn.commit()
    conn.close()

def session_valid(username):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT active_session_id FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    return row["active_session_id"] == session.get("sid")

# ======================================================
# SECURITY LAYER
# ======================================================

@app.before_request
def security():
    if request.path.startswith("/static"):
        return

    if request.endpoint in ("login", "register"):
        return

    if "user" not in session:
        return redirect("/login")

    if not session_valid(session["user"]):
        session.clear()
        return redirect("/login")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (session["user"],))
    user = cur.fetchone()
    conn.close()

    if not user or not user["is_active"] or not subscription_valid(user):
        session.clear()
        return redirect("/login")

# ======================================================
# AUTH
# ======================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cur.fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        conn.close()
        return "Login failed", 401

    if not user["is_active"]:
        conn.close()
        return "Account inactive", 403

    if not subscription_valid(user):
        conn.close()
        return "Subscription expired", 403

    register_session(username)
    conn.close()
    return redirect("/")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, subscription_end, status) VALUES (?, ?, ?, ?)",
            (
                username,
                generate_password_hash(password),
                None,
                "pending"
            )
        )
        conn.commit()
    except:
        conn.close()
        return "Username exists", 400

    conn.close()
    return redirect("/login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ======================================================
# ADMIN REQUIRED (EKSİKTİ EKLENDİ)
# ======================================================

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("user") != "admin":
            return "Unauthorized", 403
        return f(*args, **kwargs)
    return wrapper

# ======================================================
# ADMIN APPROVAL (TEKRAR ÖDEME SENARYOSU DAHİL)
# ======================================================

@app.route("/admin/approve-user", methods=["POST"])
@admin_required
def approve_user():
    data = request.json
    user_id = data.get("user_id")
    days = int(data.get("days", 30))

    invite_link = create_invite_link()

    conn = get_connection()
    cur = conn.cursor()

    new_end = datetime.now() + timedelta(days=days)

    cur.execute("""
        UPDATE users
        SET status='approved',
            subscription_end=?,
            invite_sent=1,
            invite_link=?,
            is_active=1
        WHERE id=?
    """, (
        new_end.strftime("%Y-%m-%d %H:%M:%S"),
        invite_link,
        user_id
    ))

    cur.execute("SELECT telegram_chat_id FROM users WHERE id=?", (user_id,))
    user = cur.fetchone()

    conn.commit()
    conn.close()

    if user and user["telegram_chat_id"] and invite_link:
        send_user_telegram(
            user["telegram_chat_id"],
            f"✅ Aboneliğiniz aktif edildi.\n\nYeni giriş linkiniz:\n{invite_link}"
        )

    return {"status": "approved"}

# ======================================================
# EXPIRE KONTROLÜ (YENİ EKLENDİ)
# ======================================================

def remove_expired_users():
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        SELECT id, telegram_chat_id
        FROM users
        WHERE subscription_end IS NOT NULL
        AND subscription_end < ?
        AND status='approved'
    """, (now,))

    expired = cur.fetchall()

    for u in expired:
        if u["telegram_chat_id"]:
            kick_from_channel(u["telegram_chat_id"])

        cur.execute("""
            UPDATE users
            SET status='expired',
                invite_sent=0
            WHERE id=?
        """, (u["id"],))

    conn.commit()
    conn.close()

# ======================================================
# REMINDER + EXPIRE
# ======================================================

def check_subscription_reminders():
    conn = get_connection()
    cur = conn.cursor()
    tomorrow = (datetime.now() + timedelta(days=1)).date()

    cur.execute("""
        SELECT telegram_chat_id, subscription_end
        FROM users
        WHERE is_active=1 AND status='approved'
    """)
    users = cur.fetchall()

    for u in users:
        if not u["subscription_end"]:
            continue

        end_date = datetime.strptime(u["subscription_end"], "%Y-%m-%d %H:%M:%S")

        if end_date.date() == tomorrow:
            send_user_telegram(
                u["telegram_chat_id"],
                "⚠️ Yarın aboneliğiniz sona eriyor."
            )

    conn.close()

# ======================================================
# SCANNER LOOP
# ======================================================

def scanner_loop():
    last_reminder = None

    while True:
        now = now_tr()

        remove_expired_users()

        if last_reminder != now.date():
            check_subscription_reminders()
            last_reminder = now.date()

        reset_daily_success_if_needed()
        reset_weekly_success_if_needed()

        try:
            if not is_market_open(now):
                time.sleep(30)
                continue

            market_data = fetch_bist_data()

            for item in market_data:
                symbol = item.get("symbol")
                price = item.get("current_price")

                signals = process_symbol_signals(item)
                success_hits = update_success_targets(symbol, price)

                for s in success_hits:
                    push_success_signal(s)
                    broadcast_signal(format_signal_message(s))

                for s in signals:
                    push_signal(s)
                    broadcast_signal(format_signal_message(s))

        except Exception as e:
            print("Scanner error:", e)

        time.sleep(SCAN_INTERVAL)

# ======================================================
# ROUTES
# ======================================================

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "market_open": is_market_open()
    })

# ======================================================
# START
# ======================================================

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
