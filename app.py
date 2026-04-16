import os
import time
import threading
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from functools import wraps
import random
import string


from ultra_price_engine import start_engine
from ultra_price_engine import get_price
from volume_engine import load_volume_cache, save_volume_cache
from volume_engine import get_rvol
from volume_engine import update_tick


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
from kap_monitor import check_kap
from kap_volume_signal import detect_kap_volume_momentum

from utils import FALLBACK_SYMBOLS
import dashboard
from bist_market_filters import get_brut_list
from brut_tracker import (
    detect_new_bruts,
    build_daily_message,
    build_new_message,
    safe_get_brut
)
from momentum_card import build_momentum_card
from candle_engine import get_15m_df
# ======================================================
# ENV
# ======================================================

load_dotenv()
ADMIN_PANEL_PATH = os.getenv("ADMIN_PANEL_PATH", "admin-hidden")

# ======================================================
# 🔥 ENGINE SYMBOLS (MERKEZİ)
# ======================================================
ENGINE_SYMBOLS = list(set(FALLBACK_SYMBOLS))

# ======================================================
# TIME
# ======================================================

TR_TZ = ZoneInfo("Europe/Istanbul")
BIST_OPEN = dtime(9, 40)
BIST_CLOSE = dtime(18, 5)
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "3"))

# ======================================================
# TELEGRAM
# ======================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
REPORT_CHAT_IDS = os.getenv("REPORT_CHAT_IDS", "")

REPORT_CHAT_IDS = [
    int(x.strip())
    for x in REPORT_CHAT_IDS.split(",")
    if x.strip()
]

# ======================================================
# FLASK
# ======================================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key")
app.register_blueprint(dashboard_bp)

init_db()

# ======================================================
# GLOBAL TRADE TRACK
# ======================================================
RVOL_CACHE = {}
ACTIVE_TRADES = {}
LAST_SEND_TIME = 0
# ======================================================
# 📊 MOMENTUM TRACKING
# ======================================================

MOMENTUM_TRADES = {}
# ======================================================
# RVOL ENGINE
# ======================================================

def rvol_updater():

    while True:
        try:
            for symbol in ENGINE_SYMBOLS:

                r = get_rvol(symbol)

                if r is not None:
                    RVOL_CACHE[symbol] = r

                time.sleep(0.05)  # BAN yememek için kritik

        except Exception as e:
            print("RVOL ENGINE ERROR:", e)

        time.sleep(1)
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

# ======================================================
# HELPERS
# ======================================================

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

# ======================================================
# 📸 TELEGRAM PHOTO
# ======================================================

def send_photo(chat_id, image_path, caption=None):
    import requests

    global LAST_SEND_TIME

    try:
        # 🚦 RATE LIMIT
        now = time.time()
        if now - LAST_SEND_TIME < 0.4:
            time.sleep(0.4)

        LAST_SEND_TIME = time.time()

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"

        with open(image_path, "rb") as f:
            requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "caption": caption
                },
                files={"photo": f},
                timeout=10
            )

    except Exception as e:
        print("Photo send error:", e)


def send_report_to_admins(text):
    for cid in REPORT_CHAT_IDS:
        try:
            send_user_telegram(cid, text)
        except Exception as e:
            print(f"Report send error ({cid}):", e)

def send_to_channel(text):
    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        return
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": CHANNEL_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=5
        )
    except Exception as e:
        print("Channel send error:", e)

def broadcast_signal(msg):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT telegram_chat_id
        FROM users
        WHERE is_active = 1
        AND telegram_chat_id IS NOT NULL
    """)

    users = cur.fetchall()
    conn.close()

    for u in users:
        try:
            cid = int(u["telegram_chat_id"])

            send_user_telegram(cid, msg)

            time.sleep(0.05)  # 🚦 rate limit (çok kritik)

        except Exception as e:
            print(f"Broadcast error ({cid}):", e)
# ======================================================
# 🚀 MOMENTUM SIGNAL (IMAGE + CHART)
# ======================================================

def send_momentum_signal(data):

    try:
        symbol = data.get("symbol")
        entry = data.get("entry_price")
        score = data.get("score")
        quality = data.get("quality")
        entry_type = data.get("entry_type")
        live_price = data.get("live_price")
        momentum = data.get("momentum_pct")
        vwap_dist = data.get("vwap_distance")

        # 🔥 GRAFİK DATA
        df15 = data.get("df15")

        # SAFE FORMAT
        entry = round(entry, 2) if entry is not None else 0
        live_price = round(live_price, 2) if live_price is not None else 0
        momentum = round(momentum, 2) if momentum is not None else 0
        vwap_dist = round(vwap_dist, 2) if vwap_dist is not None else 0

        # 🎯 CARD DATA
        card_data = {
            "symbol": symbol,
            "entry": entry,
            "live_price": live_price,
            "type": entry_type,
            "score": f"{score} ({quality})",
            "momentum": momentum,
            "vwap": vwap_dist,
            "df15": df15,
            "tp1": entry * 1.01
        }

        # --------------------------------------------------
        # 🖼 KART OLUŞTUR
        # --------------------------------------------------

        img_path = build_momentum_card(card_data)

        # ❌ KART OLUŞMADI → FULL FALLBACK
        if not img_path or not os.path.exists(img_path):

            fallback_msg = f"""
🚀 MOMENTUM DETAY

📊 {symbol}
💰 Giriş: {entry}
📡 Anlık: {live_price}

⚡ Tür: {entry_type}
📊 Skor: {score} ({quality})

📈 Momentum: %{momentum}
📉 VWAP: %{vwap_dist}

🧠 Yorum:
- Momentum: {"Güçlü" if momentum > 1.2 else "Orta" if momentum > 0.7 else "Zayıf"}
- VWAP: {"Uzak" if vwap_dist > 1.5 else "Sağlıklı"}

🕒 {datetime.now().strftime('%H:%M:%S')}
"""

            send_to_channel(fallback_msg)
            return

        # --------------------------------------------------
        # 🚀 GÖNDER (GÖRSEL)
        # --------------------------------------------------

        caption = f"{symbol} | {entry_type} | {score}"
        send_photo(CHANNEL_ID, img_path, caption)

        # 🧹 TEMİZLE
        try:
            os.remove(img_path)
        except:
            pass

    except Exception as e:
        print("MOMENTUM CARD ERROR:", e)

        # 🔥 FULL SAFE FALLBACK (BURASI EN KRİTİK)
        try:
            symbol = data.get("symbol", "-")
            entry = data.get("entry_price", 0)
            entry_type = data.get("entry_type", "-")
            score = data.get("score", "-")
            quality = data.get("quality", "-")
            live_price = data.get("live_price", 0)
            momentum = data.get("momentum_pct", 0)
            vwap_dist = data.get("vwap_distance", 0)

            fallback_msg = f"""
🚀 MOMENTUM (HATA SONRASI)

📊 {symbol}
💰 Giriş: {entry}
📡 Anlık: {live_price}

⚡ Tür: {entry_type}
📊 Skor: {score} ({quality})

📈 Momentum: %{momentum}
📉 VWAP: %{vwap_dist}

🕒 {datetime.now().strftime('%H:%M:%S')}
"""

            send_to_channel(fallback_msg)

        except Exception as e2:
            print("FALLBACK ERROR:", e2)
# ======================================================
# BRUT TAKAS RAPORU
# ======================================================

def build_brut_report():

    brut_map = get_brut_list()

    if not brut_map:
        return None

    lines = []

    lines.append("⚠️ BUGÜN BRÜT TAKAS OLAN HİSSELER")
    lines.append("")

    for symbol, data in sorted(brut_map.items()):

        days = data.get("days_left")

        if days is None:
            continue

        lines.append(f"{symbol.replace('.IS','')} → {days} gün")

    lines.append("")
    lines.append(f"🕒 {now_tr().strftime('%H:%M')}")

    return "\n".join(lines)
# ======================================================
# STARTUP MESSAGE
# ======================================================

def send_startup_message():

    if not ADMIN_CHAT_ID:
        return

    msg = (
        "🟢 <b> Bot Başlatıldı</b>\n"
        f"🕒 {now_tr().strftime('%H:%M:%S')} | {now_tr().strftime('%d.%m.%Y')}"
    )

    send_user_telegram(ADMIN_CHAT_ID, msg)

# ======================================================
# 📊 MOMENTUM DAILY REPORT
# ======================================================

def build_momentum_daily_report():

    if not MOMENTUM_TRADES:
        return None

    total = len(MOMENTUM_TRADES)
    success = 0
    fail = 0
    active = 0

    lines = []
    lines.append("🚀 MOMENTUM GÜN SONU RAPORU\n")

    for symbol, t in MOMENTUM_TRADES.items():

        status = t.get("status")

        if status == "success":
            success += 1
            emoji = "✅"
        elif status == "fail":
            fail += 1
            emoji = "❌"
        else:
            active += 1
            emoji = "⏳"

        entry = t.get("entry")
        exit_price = t.get("exit", "-")

        lines.append(f"{emoji} {symbol} | Giriş: {entry} → {exit_price}")

    lines.append("\n📊 ÖZET")
    lines.append(f"Toplam: {total}")
    lines.append(f"✅ Başarılı: {success}")
    lines.append(f"❌ Başarısız: {fail}")
    lines.append(f"⏳ Açık: {active}")

    success_rate = round((success / total) * 100, 2) if total > 0 else 0
    lines.append(f"\n📈 Başarı Oranı: %{success_rate}")

    lines.append(f"\n🕒 {now_tr().strftime('%H:%M')}")

    return "\n".join(lines)
# ======================================================
# 🔄 MOMENTUM RESET
# ======================================================

def reset_momentum_if_needed(last_reset_date, now):

    if last_reset_date != now.date() and now.time() > BIST_CLOSE:
        MOMENTUM_TRADES.clear()
        return now.date()

    return last_reset_date
# ======================================================
# INVITE CODE
# ======================================================

def validate_invite_code(code):
    if not code:
        return False
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, is_used, expires_at FROM invite_codes WHERE code=?", (code,))
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
        SET is_used=1, used_by=?
        WHERE code=?
    """, (username, code))
    conn.commit()
    conn.close()

# ======================================================
# SESSION
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

    if request.path.startswith("/api/dashboard") or request.path == "/health":
        return

    if request.path.startswith(f"/{ADMIN_PANEL_PATH}") or request.path.startswith("/admin"):
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

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("user") != "admin":
            return "Unauthorized", 403
        return f(*args, **kwargs)
    return wrapper

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
# INDEX
# ======================================================

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/health")
def health():
    return jsonify({
        "market_open": is_market_open(),
        "server_time": now_tr().strftime("%H:%M:%S")
    })

# ======================================================
# ADMIN PANEL
# ======================================================

@app.route(f"/{ADMIN_PANEL_PATH}")
def admin_panel():
    return render_template("admin.html")

@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, telegram_chat_id,
               subscription_end, status, is_active
        FROM users ORDER BY id DESC
    """)
    users = cur.fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route("/admin/delete-user", methods=["POST"])
@admin_required
def delete_user():
    data = request.json
    user_id = data.get("user_id")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route("/admin/update-subscription", methods=["POST"])
@admin_required
def update_subscription():
    data = request.json
    user_id = data.get("user_id")
    days = int(data.get("days", 0))
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    now = datetime.now()
    if row and row["subscription_end"]:
        current_end = datetime.strptime(row["subscription_end"], "%Y-%m-%d %H:%M:%S")
        if current_end > now:
            new_end = current_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
    else:
        new_end = now + timedelta(days=days)
    cur.execute("""
        UPDATE users
        SET subscription_end=?, status='approved', is_active=1, expiry_warning_sent=0
        WHERE id=?
    """, (new_end.strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/admin/invite-codes")
@admin_required
def admin_invite_codes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT code, is_used, used_by, created_at
        FROM invite_codes ORDER BY created_at DESC
    """)
    codes = cur.fetchall()
    conn.close()
    return jsonify([dict(c) for c in codes])

@app.route("/admin/delete-code", methods=["POST"])
@admin_required
def admin_delete_code():
    data = request.json
    code = data.get("code")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM invite_codes WHERE code=?", (code,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route("/admin/generate-codes", methods=["POST"])
@admin_required
def generate_invite_codes():
    data = request.json or {}

    count = int(data.get("count", 5))
    expire_days = data.get("expire_days")

    try:
        expire_days = int(expire_days) if expire_days else None
    except:
        expire_days = None

    conn = get_connection()
    cur = conn.cursor()

    created_codes = []

    for _ in range(count):
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            cur.execute("SELECT id FROM invite_codes WHERE code=?", (code,))
            if not cur.fetchone():
                break

        created_at = datetime.now()
        expires_at = created_at + timedelta(days=expire_days) if expire_days else None

        cur.execute("""
            INSERT INTO invite_codes
            (code, is_used, created_at, expires_at)
            VALUES (?, 0, ?, ?)
        """, (
            code,
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            expires_at.strftime("%Y-%m-%d %H:%M:%S") if expires_at else None
        ))

        created_codes.append(code)

    conn.commit()
    conn.close()

    return jsonify({
        "status": "created",
        "count": len(created_codes),
        "codes": created_codes
    })

def scanner_loop():

    send_startup_message()
    
    last_fetch_time = 0
    FETCH_INTERVAL = 5
    last_market_data = []
    kap_cache = {}
    last_kap_check = 0
    KAP_INTERVAL = 25

    last_brut_report = None
    last_daily_report = None
    last_weekly_report = None
    last_momentum_reset = None

    while True:

        now = now_tr()

        print(f"\n⏱ Döngü: {now.strftime('%H:%M:%S')}", flush=True)

        reset_daily_success_if_needed()
        reset_weekly_success_if_needed()

        dashboard.SYSTEM_ACTIVE = False

        try:

            # --------------------------------------------------
            # MARKET KAPALI
            # --------------------------------------------------

            if not is_market_open(now):

                print("⏹ Market kapalı", flush=True)

                dashboard.SYSTEM_ACTIVE = False

                if last_daily_report != now.date() and now.time() > BIST_CLOSE:

                    report = build_daily_success_report()

                    if report:
                        send_report_to_admins(report)

                    m_report = build_momentum_daily_report()
                    if m_report:
                        send_to_channel(m_report)

                    last_momentum_reset = reset_momentum_if_needed(last_momentum_reset, now)

                    last_daily_report = now.date()

                if now.weekday() == 4 and now.time() >= dtime(18, 10):

                    week_id = now.strftime("%Y-%W")

                    if last_weekly_report != week_id:

                        report = build_weekly_success_report()

                        if report:
                            send_report_to_admins(report)

                        last_weekly_report = week_id

                time.sleep(30)
                continue

            # --------------------------------------------------
            # MARKET AÇIK
            # --------------------------------------------------

            dashboard.SYSTEM_ACTIVE = True
            print("✅ MARKET AÇIK → TARAMA", flush=True)

            # --------------------------------------------------
            # BRUT TAKAS RAPORU
            # --------------------------------------------------

            if (
                last_brut_report != now.date()
                and now.weekday() < 5
                and now.time() >= dtime(9, 40)
            ):

                msg = build_daily_message(now)

                if msg:
                    send_to_channel(msg)

                last_brut_report = now.date()

            now_ts = time.time()

            # --------------------------------------------------
            # KAP TARAMA
            # --------------------------------------------------

            if now_ts - last_kap_check > KAP_INTERVAL:

                try:

                    new_kaps = check_kap(ENGINE_SYMBOLS)

                    if new_kaps:

                        kap_cache.update(new_kaps)

                        if len(kap_cache) > 500:
                            kap_cache = dict(list(kap_cache.items())[-200:])

                except Exception as e:
                    print("KAP tarama hatası:", e)

                # 🔥 YENİ BRÜT TAKAS KONTROL
                try:
                    new_bruts = detect_new_bruts()

                    if new_bruts and len(new_bruts) > 0:
                        msg = build_new_message(new_bruts, now_tr())
                        if msg:
                            send_to_channel(msg)

                except Exception as e:
                    print("BRUT ERROR:", e)

                last_kap_check = time.time()

            # --------------------------------------------------
            # MARKET DATA
            # --------------------------------------------------

            # --------------------------------------------------
            # MARKET DATA (NON-BLOCKING)
            # --------------------------------------------------

            if time.time() - last_fetch_time > FETCH_INTERVAL:
                new_data = fetch_bist_data(ENGINE_SYMBOLS)
                if isinstance(new_data, list):
                    if len(new_data) > 0:
                        last_market_data = new_data
                    else:
                        print("⚠ boş veri geldi, eski veri korunuyor")
                last_fetch_time = time.time()

            market_data = last_market_data or []

            if len(market_data) == 0:
                print("⚠ Veri alınamadı → sinyal durduruldu", flush=True)
                time.sleep(60)
                continue

            market_data = market_data[:250]

            valid_count = 0

            for x in market_data:
                try:
                    price = x.get("current_price")
                    symbol = x.get("symbol")

                    if symbol and isinstance(price, (int, float)) and price > 0:
                        valid_count += 1
                except:
                    continue

            threshold = max(20, int(len(market_data) * 0.35))
            if valid_count < threshold:
                print(
                    f"⚠ Sağlıksız veri → valid={valid_count} / total={len(market_data)} / threshold={threshold}",
                    flush=True
                )
                time.sleep(60)
                continue

            # ==================================================
            # 🔁 MAIN LOOP
            # ==================================================

            for item in market_data:

                symbol = item.get("symbol")
                price = item.get("current_price")

                # 🔥 ENGINE PRICE FALLBACK
                if not price or price == 0:
                    price = get_price(symbol)

                # 🔥 .IS uyumsuzluğu için
                if not price and symbol:
                    clean_symbol = symbol.replace(".IS", "")
                    price = get_price(clean_symbol)

                # 🔥 REALTIME PRICE FORCE
                live_price = get_price(symbol)

                if live_price is not None and live_price > 0:
                    price = live_price
                    item["current_price"] = price

                # ❌ hala yoksa skip
                if not price:
                    continue

                # 🔥 artık güvenli şekilde kullanabilirsin
                item["current_price"] = price
                item["timestamp"] = time.time()
                update_tick(symbol, price)
                rvol = get_rvol(symbol)
                

                if rvol is None:
                    rvol = 0

                item["rvol"] = rvol


                if symbol and isinstance(price, (int, float)):
                    dashboard.LIVE_PRICES[symbol] = price


                try:

                    # ==================================================
                    # 🎯 TARGET TRACKING
                    # ==================================================

                    if symbol in ACTIVE_TRADES:

                        trade = ACTIVE_TRADES[symbol]

                        entry = trade["entry"]
                        target = trade["target"]

                        if price >= target:

                            msg = f"""
🎯 HEDEF GERÇEKLEŞTİ

📊 {symbol}

💰 Giriş: {entry}
🏁 Çıkış: {price}

📈 Getiri: %{round((price-entry)/entry*100,2)}
"""

                            send_to_channel(msg)
                            del ACTIVE_TRADES[symbol]

                        elif price <= entry * 0.95:

                            msg = f"""
⛔ BAŞARISIZ

📊 {symbol}

💰 Giriş: {entry}
📉 Fiyat: {price}

Zarar: %{round((price-entry)/entry*100,2)}
"""

                            send_to_channel(msg)
                            del ACTIVE_TRADES[symbol]


                    # ==================================================
                    # 📊 MOMENTUM RESULT TRACK
                    # ==================================================

                    if symbol in MOMENTUM_TRADES:

                        m_trade = MOMENTUM_TRADES[symbol]
                        entry = m_trade["entry"]

                        if m_trade.get("status") == "active":

                            if price >= entry * 1.01:
                                m_trade["status"] = "success"
                                m_trade["exit"] = price

                            elif price <= entry * 0.95:
                                m_trade["status"] = "fail"
                                m_trade["exit"] = price

                    # --------------------------------------------------
                    # 🚀 KAP MOMENTUM
                    # --------------------------------------------------

                    kap_signal = detect_kap_volume_momentum(item, kap_cache)

                    if kap_signal and kap_signal.get("entry_price"):

                        try:
                            import pandas as pd

                            df = get_15m_df(symbol, live_price=price)

                            if df is not None:

                                if not isinstance(df, pd.DataFrame):
                                    df = pd.DataFrame(df)

                                df.columns = [c.lower() for c in df.columns]
                                df = df.dropna()

                                if len(df) > 10 and all(c in df.columns for c in ["open", "high", "low", "close"]):

                                    kap_signal["df15"] = df
                                    print(f"✅ DF OK: {symbol} | len={len(df)}")

                                else:
                                    print(f"❌ DF ZAYIF: {symbol} | len={len(df)}")
                                    kap_signal["df15"] = None

                            else:
                                print("❌ DF yok:", symbol)
                                kap_signal["df15"] = None

                        except Exception as e:
                            print("DF ERROR:", e)
                            kap_signal["df15"] = None

                        kap_signal["live_price"] = float(price)

                        kap_symbol = kap_signal["symbol"]

                        if not kap_cache.get(kap_symbol, {}).get("alert_sent"):

                            entry_price = kap_signal["entry_price"]
                            target_price = entry_price * 1.01

                            ACTIVE_TRADES[kap_symbol] = {
                                "entry": entry_price,
                                "target": target_price,
                                "time": now
                            }

                            send_momentum_signal(kap_signal)

                            # 📊 MOMENTUM TRACK
                            MOMENTUM_TRADES[kap_symbol] = {
                                "entry": entry_price,
                                "time": now,
                                "status": "active"
                            }

                            kap_cache.setdefault(kap_symbol, {})["alert_sent"] = True

                    # --------------------------------------------------
                    # NORMAL ENGINE
                    # --------------------------------------------------

                    signals = process_symbol_signals(item)

                    success_hits = update_success_targets(symbol, price)

                    for s in success_hits:

                        push_success_signal(s)

                        msg = format_signal_message(s)

                        if s.get("main_algorithm") == "SCALPING":
                            send_to_channel(msg)
                        else:
                            broadcast_signal(msg)

                    for s in signals:

                        push_signal(s)

                        msg = format_signal_message(s)

                        if s.get("main_algorithm") == "SCALPING":
                            send_to_channel(msg)
                        else:
                            broadcast_signal(msg)

                except Exception as e:
                    print(f"⚠ {symbol} hata:", e, flush=True)

        except Exception as e:
            print("🔥 Scanner genel hata:", e, flush=True)

        time.sleep(SCAN_INTERVAL)


# ======================================================
# START
# ======================================================

if __name__ == "__main__":

    # ==================================================
    # 🔥 ULTRA ENGINE START
    # ==================================================
    print("🚀 ULTRA PRICE ENGINE STARTING...")

    start_engine(ENGINE_SYMBOLS)

    # ==================================================
    # 🔥 VOLUME ENGINE START
    # ==================================================
    print("📊 VOLUME ENGINE STARTING...")

    load_volume_cache()
    threading.Thread(target=save_volume_cache, daemon=True).start()
   
    # 🔥 RVOL BACKGROUND ENGINE
    threading.Thread(target=rvol_updater, daemon=True).start()

    # ==================================================
    # 🔁 SCANNER START
    # ==================================================
    threading.Thread(target=scanner_loop, daemon=True).start()

    # ==================================================
    # 🌐 WEB
    # ==================================================
    app.run(host="0.0.0.0", port=5000, debug=False)
