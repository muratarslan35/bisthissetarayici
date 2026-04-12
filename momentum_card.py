from PIL import Image, ImageDraw, ImageFont
import os

WIDTH = 900
HEIGHT = 600

BG = (10, 15, 25)
CARD = (18, 25, 40)

WHITE = (255, 255, 255)
GREEN = (0, 220, 120)
YELLOW = (255, 190, 0)
GRAY = (180, 180, 180)

# --------------------------------------------------
# BAR
# --------------------------------------------------

def build_bar(value, max_blocks=10):
    filled = int(min(max(value / 2, 0), 1) * max_blocks)
    return "▰" * filled + "▱" * (max_blocks - filled)

# --------------------------------------------------
# YORUMLAR
# --------------------------------------------------

def momentum_comment(val):
    if val >= 1.5:
        return "🟢 Güçlü Momentum → Trend hızlanıyor"
    elif val >= 0.7:
        return "🟡 Erken Güçlenme → Kurumsal giriş"
    else:
        return "⚪ Zayıf Momentum → Riskli"

def vwap_comment(val):
    if val >= 1.5:
        return "🔴 Aşırı uzak → Düzeltme riski"
    elif val >= 0.5:
        return "🟡 Ortalama üstü → Trend sağlıklı"
    else:
        return "🟢 VWAP yakın → Güvenli giriş"

# --------------------------------------------------
# ANA KART
# --------------------------------------------------

def build_momentum_card(data):

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    font_big = ImageFont.load_default()
    font_mid = ImageFont.load_default()
    font_small = ImageFont.load_default()

    # CARD
    draw.rectangle([30, 30, WIDTH-30, HEIGHT-30], fill=CARD)

    # HEADER
    draw.text((60, 60), f"{data['symbol']}", fill=WHITE, font=font_big)
    draw.text((500, 60), "🚀 MOMENTUM", fill=YELLOW, font=font_big)

    # ENTRY
    draw.text((60, 120), f"Giriş: {data['entry']}", fill=WHITE, font=font_mid)

    # TYPE
    draw.text((60, 150), f"{data['type']} | {data['score']}", fill=GRAY, font=font_small)

    # ----------------------------
    # MOMENTUM BLOK
    # ----------------------------
    m = data["momentum"]

    draw.text((60, 230), f"💹 Momentum: %{m}", fill=GREEN, font=font_mid)
    draw.text((60, 260), momentum_comment(m), fill=WHITE, font=font_small)
    draw.text((60, 290), build_bar(m), fill=GREEN, font=font_mid)

    # ----------------------------
    # VWAP BLOK
    # ----------------------------
    v = data["vwap"]

    draw.text((60, 350), f"📉 VWAP: %{v}", fill=YELLOW, font=font_mid)
    draw.text((60, 380), vwap_comment(v), fill=WHITE, font=font_small)
    draw.text((60, 410), build_bar(v), fill=YELLOW, font=font_mid)

    # ----------------------------
    # KARAR
    # ----------------------------
    draw.text((60, 480), "🧠 KARAR: STRONG ENTRY", fill=GREEN, font=font_mid)

    # SAVE
    os.makedirs("cards", exist_ok=True)
    path = f"cards/{data['symbol']}.png"
    img.save(path)

    return path
