import os
import time
import threading
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from functools import wraps

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
ADMIN_PANEL_PATH = os.getenv("ADMIN_PANEL_PATH", "admin-hidden")

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
    except Exception as e:
        print("Telegram send error:", e)

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
# STARTUP MESSAGE
# ======================================================

def send_startup_message():
    broadcast_signal(
        "🟢 <b>HİSSE TARAMA SİSTEMİ BAŞLATILDI</b>\n"
        f"🕒 {now_tr().strftime('%H:%M:%S')} | {now_tr().strftime('%d.%m.%Y')}"
    )

# ======================================================
# INVITE CODE CONTROL
# ======================================================

def validate_invite_code(code):
    if not code:
        return False

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, is_used, expires_at
        FROM invite_codes
        WHERE code=?
    """, (code,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return False

    if row["is_used"] == 1:
        conn.close()
        return False

    if row["expires_at"]:
        expire_time = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        if expire_time < datetime.now():
            conn.close()
            return False

    conn.close()
    return True

def mark_invite_code_used(code, username):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE invite_codes
        SET is_used=1,
            used_by=?
        WHERE code=?
    """, (username, code))
    conn.commit()
    conn.close()

# ======================================================
# SESSION CONTROL
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
# SECURITY
# ======================================================

@app.before_request
def security():
    if request.path.startswith("/static"):
        return

    if request.path in ("/login", "/register"):
        return

    if request.path.startswith(f"/{ADMIN_PANEL_PATH}"):
        if session.get("user") != "admin":
            return "Unauthorized", 403
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
# ADMIN DECORATOR
# ======================================================

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("user") != "admin":
            return "Unauthorized", 403
        return f(*args, **kwargs)
    return wrapper

# ======================================================
# AUTH ROUTES
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

    register_session(username)
    conn.close()
    return redirect("/")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username")
    password = request.form.get("password")
    invite_code = request.form.get("invite_code")

    if not validate_invite_code(invite_code):
        return "Invalid or expired invite code", 400

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, subscription_end, status) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), None, "pending")
        )
        conn.commit()
        mark_invite_code_used(invite_code, username)
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
# ADMIN PANEL ROUTE
# ======================================================

@app.route(f"/{ADMIN_PANEL_PATH}")
def admin_panel():
    return render_template("admin.html")

# ======================================================
# ADMIN API ENDPOINTS
# ======================================================

@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, telegram_chat_id,
               subscription_end, status, is_active
        FROM users
        ORDER BY id DESC
    """)
    users = cur.fetchall()
    conn.close()

    return jsonify([
        dict(u) for u in users
    ])

# ======================================================
# FULL PRODUCTION SCANNER
# ======================================================

def scanner_loop():
    send_startup_message()

    last_daily_report = None
    last_weekly_report = None
    last_close_snapshot_date = None

    while True:
        now = now_tr()
        print(f"\n⏱ Döngü: {now.strftime('%H:%M:%S')}", flush=True)

        reset_daily_success_if_needed()
        reset_weekly_success_if_needed()

        try:
            if not is_market_open(now):
                print("⏹ Market kapalı", flush=True)

                if now.time() >= dtime(18, 10) and last_close_snapshot_date != now.date():
                    try:
                        print("📌 Snapshot alınıyor...", flush=True)
                        market_data = fetch_bist_data()
                        for item in market_data:
                            update_success_targets(
                                item["symbol"],
                                item["current_price"]
                            )
                        last_close_snapshot_date = now.date()
                        print("✅ Snapshot tamamlandı", flush=True)
                    except Exception as e:
                        print("Snapshot error:", e)

                if last_daily_report != now.date() and now.time() > BIST_CLOSE:
                    report = build_daily_success_report()
                    if report:
                        broadcast_signal(report)
                    last_daily_report = now.date()

                if now.weekday() == 4 and now.time() >= dtime(18, 10):
                    week_id = now.strftime("%Y-%W")
                    if last_weekly_report != week_id:
                        report = build_weekly_success_report()
                        if report:
                            broadcast_signal(report)
                        last_weekly_report = week_id

                time.sleep(30)
                continue

            print("✅ MARKET AÇIK → TARAMA", flush=True)

            market_data = fetch_bist_data()

            for item in market_data:
                symbol = item.get("symbol")
                price = item.get("current_price")

                try:
                    signals = process_symbol_signals(item)
                    success_hits = update_success_targets(symbol, price)

                    for s in success_hits:
                        push_success_signal(s)
                        broadcast_signal(format_signal_message(s))

                    for s in signals:
                        push_signal(s)
                        broadcast_signal(format_signal_message(s))

                except Exception as e:
                    print(f"⚠ {symbol} hata:", e)

        except Exception as e:
            print("🔥 Scanner genel hata:", e)

        time.sleep(SCAN_INTERVAL)

# ======================================================
# START
# ======================================================

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
