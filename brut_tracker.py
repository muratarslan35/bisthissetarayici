import json
import os
from bist_market_filters import get_brut_list
from datetime import datetime

STATE_FILE = "data/brut_state.json"

# ======================================================
# STATE
# ======================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print("STATE LOAD ERROR:", e)
        return {}


def save_state(data):
    try:
        os.makedirs("data", exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("STATE SAVE ERROR:", e)


# ======================================================
# SAFE BRUT FETCH (EN KRİTİK)
# ======================================================

def safe_get_brut():
    try:
        data = get_brut_list()

        # ✅ GERÇEK DATA GELDİ
        if data and isinstance(data, dict) and len(data) > 0:
            print(f"✅ BRUT OK → {len(data)} adet")
            return data  # ❗ BURADA SAVE YOK

        # ⚠ FALLBACK
        print("⚠ BRUT BOŞ → CACHE KULLANILIYOR")
        cached = load_state()

        if cached:
            print(f"📦 CACHE BRUT → {len(cached)} adet")
        else:
            print("❌ CACHE DE BOŞ")

        return cached

    except Exception as e:
        print("❌ BRUT ÇEKME HATASI:", e)

        cached = load_state()

        if cached:
            print(f"📦 CACHE BRUT → {len(cached)} adet")
        else:
            print("❌ CACHE DE BOŞ")

        return cached


# ======================================================
# YENİ BRÜT TESPİT
# ======================================================

def detect_new_bruts():

    current = safe_get_brut()
    old = load_state()

    # 🧠 İLK ÇALIŞMA KORUMA
    if not old:
        print("ℹ İlk çalıştırma → cache oluşturuluyor")
        if current:
            save_state(current)
        return {}

    new = {}

    for sym, data in current.items():
        if sym not in old:
            new[sym] = data

    # ✅ SADECE DOLU DATA VARSA SAVE
    if current and len(current) > 0:
        save_state(current)

    print(f"🆕 YENİ BRUT: {len(new)} adet")

    return new


# ======================================================
# GÜNLÜK MESAJ
# ======================================================

def build_daily_message(now):

    brut = safe_get_brut()

    if not brut:
        print("❌ GÜNLÜK BRUT YOK")
        return None

    lines = []
    lines.append("📊 <b>GÜNLÜK BRÜT TAKAS LİSTESİ</b>")
    lines.append(f"📅 {now.strftime('%d.%m.%Y')}")
    lines.append("────────────")

    for sym, d in sorted(brut.items()):

        name = sym.replace(".IS","")

        lines.append(f"📌 <b>{name}</b>")
        lines.append(f"🟢 Başlangıç: {d.get('start_date','-')}")
        lines.append(f"🔴 Bitiş: {d.get('end_date','-')}")
        lines.append(f"⏳ Kalan: {d.get('days_left','?')} gün")
        lines.append(f"⚠️ {d.get('type','Brüt Takas')}")
        lines.append("────────────")

    print(f"📤 GÜNLÜK BRUT GÖNDERİLDİ → {len(brut)} adet")

    return "\n".join(lines)


# ======================================================
# YENİ BRÜT MESAJI
# ======================================================

def build_new_message(new, now):

    if not new:
        return None

    lines = []
    lines.append("🚨 <b>YENİ BRÜT TAKAS</b>")
    lines.append("────────────")

    for sym, d in new.items():

        name = sym.replace(".IS","")

        lines.append(f"📌 <b>{name}</b>")
        lines.append(f"🟢 Başlangıç: {d.get('start_date','-')}")
        lines.append(f"🔴 Bitiş: {d.get('end_date','-')}")
        lines.append(f"⏳ {d.get('days_left','?')} gün")
        lines.append(f"⚠️ {d.get('type','Brüt Takas')}")
        lines.append("────────────")

    lines.append(f"🕒 {now.strftime('%H:%M:%S')}")

    print(f"🚨 YENİ BRUT MESAJI → {len(new)} adet")

    return "\n".join(lines)
