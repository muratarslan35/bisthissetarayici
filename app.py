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
# TELEGRAM CHANNEL CONTROL
# ======================================================

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

    # ADMIN MUAF
    if session.get("user") == "admin":
        return

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
    invite_code = request.form.get("invite_code")

    if not validate_invite_code(invite_code):
        return "Invalid or expired invite code", 400

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
# ADMIN REQUIRED
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
# ADMIN APPROVAL (BOT UYUMLU)
# ======================================================

@app.route("/admin/approve-user", methods=["POST"])
@admin_required
def approve_user():
    data = request.json
    user_id = data.get("user_id")
    days = int(data.get("days", 30))

    conn = get_connection()
    cur = conn.cursor()

    new_end = datetime.now() + timedelta(days=days)

    cur.execute("""
        UPDATE users
        SET status='approved',
            subscription_end=?,
            invite_sent=0,
            is_active=1
        WHERE id=?
    """, (
        new_end.strftime("%Y-%m-%d %H:%M:%S"),
        user_id
    ))

    conn.commit()
    conn.close()

    return {"status": "approved"}

# ======================================================
# SCANNER LOOP
# ======================================================

def scanner_loop():
    while True:
        now = now_tr()

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
