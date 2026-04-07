import json
import os
from bist_market_filters import get_brut_list
from datetime import datetime

STATE_FILE = "data/brut_state.json"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(data):
    os.makedirs("data", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def detect_new_bruts():
    current = get_brut_list() or {}
    old = load_state()

    new = {}

    for sym, data in current.items():
        if sym not in old:
            new[sym] = data

    save_state(current)

    return new

def build_daily_message(now):
    brut = get_brut_list() or {}

    if not brut:
        return None

    lines = []
    lines.append("📊 <b>GÜNLÜK BRÜT TAKAS LİSTESİ</b>")
    lines.append(f"📅 {now.strftime('%d.%m.%Y')}")
    lines.append("────────────")

    for sym, d in brut.items():
        name = sym.replace(".IS","")

        lines.append(f"📌 <b>{name}</b>")
        lines.append(f"🟢 Başlangıç: {d.get('start_date')}")
        lines.append(f"🔴 Bitiş: {d.get('end_date')}")
        lines.append(f"⏳ Kalan: {d.get('days_left')} gün")
        lines.append(f"⚠️ {d.get('type','Brüt Takas')}")
        lines.append("────────────")

    return "\n".join(lines)

def build_new_message(new, now):

    if not new:
        return None

    lines = []
    lines.append("🚨 <b>YENİ BRÜT TAKAS</b>")
    lines.append("────────────")

    for sym, d in new.items():
        name = sym.replace(".IS","")

        lines.append(f"📌 <b>{name}</b>")
        lines.append(f"🟢 Başlangıç: {d.get('start_date')}")
        lines.append(f"🔴 Bitiş: {d.get('end_date')}")
        lines.append(f"⏳ {d.get('days_left')} gün")
        lines.append(f"⚠️ {d.get('type','Brüt Takas')}")
        lines.append("────────────")

    lines.append(f"🕒 {now.strftime('%H:%M:%S')}")

    return "\n".join(lines)
