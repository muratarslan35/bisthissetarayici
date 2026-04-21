from PIL import Image, ImageDraw, ImageFont
import os

WIDTH = 1000
HEIGHT = 600

BG_TOP = (10, 15, 25)
BG_BOTTOM = (5, 10, 18)

WHITE = (255, 255, 255)
GREEN = (0, 255, 160)
RED = (255, 70, 70)
YELLOW = (255, 190, 0)
BLUE = (0, 200, 255)
GRAY = (140, 150, 170)

# --------------------------------------------------
# FONT
# --------------------------------------------------

def get_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

# --------------------------------------------------
# BG
# --------------------------------------------------

def draw_gradient(draw):
    for i in range(HEIGHT):
        ratio = i / HEIGHT
        r = int(BG_TOP[0] * (1 - ratio) + BG_BOTTOM[0] * ratio)
        g = int(BG_TOP[1] * (1 - ratio) + BG_BOTTOM[1] * ratio)
        b = int(BG_TOP[2] * (1 - ratio) + BG_BOTTOM[2] * ratio)
        draw.line([(0, i), (WIDTH, i)], fill=(r, g, b))

# --------------------------------------------------
# GRID
# --------------------------------------------------

def draw_grid(draw, x, y, w, h):
    for i in range(5):
        yy = y + i * (h / 4)
        draw.line([x, yy, x + w, yy], fill=(30, 40, 60), width=1)

# --------------------------------------------------
# CANDLES
# --------------------------------------------------

def draw_candles(draw, df, x, y, w, h):

    if df is None or len(df) < 10:
        return

    df = df.tail(60)

    highs = df["high"].max()
    lows = df["low"].min()

    if highs == lows:
        return

    def py(p):
        return y + h - (p - lows) / (highs - lows) * h

    candle_w = w / len(df)

    for i, (_, row) in enumerate(df.iterrows()):

        cx = x + i * candle_w + candle_w * 0.2

        o = float(row["open"])
        c = float(row["close"])
        hi = float(row["high"])
        lo = float(row["low"])

        color = GREEN if c >= o else RED

        draw.line(
            [cx + candle_w * 0.3, py(hi), cx + candle_w * 0.3, py(lo)],
            fill=color,
            width=2
        )

        top = py(max(o, c))
        bot = py(min(o, c))

        if abs(top - bot) < 1:
            bot = top + 1

        draw.rectangle(
            [cx, top, cx + candle_w * 0.7, bot],
            fill=color
        )

# --------------------------------------------------
# VOLUME
# --------------------------------------------------

def draw_volume(draw, df, x, y, w, h):

    if df is None or len(df) < 10:
        return

    df = df.tail(30)

    max_vol = df["volume"].max()
    if max_vol == 0:
        return

    bar_w = w / len(df)

    for i, (_, row) in enumerate(df.iterrows()):

        cx = x + i * bar_w + bar_w * 0.2

        vol = float(row["volume"])
        o = float(row["open"])
        c = float(row["close"])

        bar_h = (vol / max_vol) * h
        color = GREEN if c >= o else RED

        draw.rectangle([
            cx,
            y + h - bar_h,
            cx + bar_w * 0.6,
            y + h
        ], fill=color)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

def build_momentum_card(data):

    try:
        img = Image.new("RGB", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(img)

        draw_gradient(draw)

        font_big = get_font(38)      # küçüldü
        font_mid = get_font(22)
        font_small = get_font(15)
        font_price = get_font(30)

        # HEADER
        symbol = data.get("symbol", "")
        draw.text((40, 30), symbol, fill=WHITE, font=font_big)
        draw.text((620, 30), "MOMENTUM ANALİZ", fill=YELLOW, font=font_mid)

        # PRICES
        entry = float(data.get("entry", 0) or 0)
        live = float(data.get("live_price", 0) or 0)
        tp1 = float(data.get("tp1", 0) or 0)

        draw.text((40, 85), "Giriş", fill=GRAY, font=font_small)
        draw.text((40, 110), f"{entry:.2f}", fill=WHITE, font=font_price)

        draw.text((200, 85), "Anlık", fill=GRAY, font=font_small)
        draw.text((200, 110), f"{live:.2f}", fill=GREEN, font=font_price)

        if tp1 > 0:
            draw.text((360, 85), "TP1", fill=GRAY, font=font_small)
            draw.text((360, 110), f"{tp1:.2f}", fill=BLUE, font=font_price)

        # 🔥 GRAFİK KÜÇÜLDÜ
        chart_x, chart_y = 40, 150
        chart_w, chart_h = 520, 280   # küçültüldü

        volume_h = 80
        price_h = chart_h - volume_h - 10

        draw_grid(draw, chart_x, chart_y, chart_w, price_h)

        df = data.get("df15")

        if df is not None:
            df = df.dropna()

            draw_candles(draw, df, chart_x, chart_y, chart_w, price_h)
            draw_volume(draw, df, chart_x, chart_y + price_h + 10, chart_w, volume_h)

        # 🔥 SAĞ PANEL GENİŞLEDİ
        px = 600

        m = float(data.get("momentum", 0))
        v = float(data.get("vwap", 0))

        draw.text((px, 140), f"Momentum Gücü: %{m:.2f}", fill=GREEN, font=font_mid)
        draw.text((px, 170), "▰" * int(min(m*5,10)), fill=GREEN, font=font_mid)

        draw.text((px, 220), f"VWAP Mesafe: %{v:.2f}", fill=YELLOW, font=font_mid)
        draw.text((px, 250), "▰" * int(min(v*5,10)), fill=YELLOW, font=font_mid)

        # DECISION
        decision = "RİSKLİ"
        color = RED

        if m > 1.2 and v < 1.5:
            decision = "GÜÇLÜ AL"
            color = GREEN
        elif m > 0.7:
            decision = "TREND BAŞLIYOR"
            color = YELLOW

        # 🔥 TAŞMA FIX
        draw.text((px, 330), "Karar:", fill=WHITE, font=font_mid)
        draw.text((px, 360), decision[:18], fill=color, font=get_font(32))

        # SAVE
        os.makedirs("cards", exist_ok=True)
        path = f"cards/{symbol}.png"
        img.save(path)

        return path

    except Exception as e:
        print("CARD ERROR:", e)
        return None
