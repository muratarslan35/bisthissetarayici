from PIL import Image, ImageDraw, ImageFont
import os

WIDTH = 1200
HEIGHT = 750

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

def draw_ema(draw, df, x, y, w, h, col, color):

    if df is None or col not in df.columns:
        return

    highs = df["high"].max()
    lows = df["low"].min()

    if highs == lows:
        return

    def py(p):
        return y + h - (p - lows) / (highs - lows) * h

    step = w / len(df)

    points = []
    for i, v in enumerate(df[col].values):
        px = x + i * step
        points.append((px, py(v)))

    if len(points) > 1:
        draw.line(points, fill=color, width=2)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

def build_momentum_card(data):

    try:
        img = Image.new("RGB", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(img)

        draw_gradient(draw)

        font_big = get_font(42)
        font_mid = get_font(22)
        font_small = get_font(15)
        font_price = get_font(30)

        symbol = data.get("symbol", "")

        draw.text((40, 30), symbol, fill=WHITE, font=font_big)
        draw.text((750, 30), "MOMENTUM ANALİZ", fill=YELLOW, font=font_mid)

        entry = float(data.get("entry", 0) or 0)
        live = float(data.get("live_price", 0) or 0)
        tp1 = float(data.get("tp1", 0) or 0)

        draw.text((40, 90), "GİRİŞ", fill=GRAY, font=font_small)
        draw.text((40, 115), f"{entry:.2f}", fill=WHITE, font=font_price)

        draw.text((200, 90), "ANLIK", fill=GRAY, font=font_small)
        draw.text((200, 115), f"{live:.2f}", fill=GREEN, font=font_price)

        draw.text((360, 90), "TP1", fill=GRAY, font=font_small)
        draw.text((360, 115), f"{tp1:.2f}", fill=BLUE, font=font_price)

        # ---------------- 15M ----------------
        df15 = data.get("df15")

        draw.text((40, 140), "15 DK GRAFİK", fill=GREEN, font=font_small)

        if df15 is not None:
            df15 = df15.tail(60).dropna()

            draw_grid(draw, 40, 160, 700, 220)
            draw_candles(draw, df15, 40, 160, 700, 220)
            draw_volume(draw, df15, 40, 380, 700, 60)

        # ---------------- 1H ----------------
        df1h = data.get("df1h")

        draw.text((40, 460), "1 SAAT GRAFİK", fill=YELLOW, font=font_small)

        if df1h is not None:
            df1h = df1h.tail(60).dropna()

            draw_grid(draw, 40, 480, 700, 180)
            draw_candles(draw, df1h, 40, 480, 700, 180)
            draw_volume(draw, df1h, 40, 660, 700, 60)

            draw_ema(draw, df1h, 40, 480, 700, 180, "ema20", BLUE)
            draw_ema(draw, df1h, 40, 480, 700, 180, "ema50", YELLOW)

        # ---------------- RIGHT PANEL ----------------
        px = 780

        m = float(data.get("momentum", 0))
        v = float(data.get("vwap", 0))

        draw.text((px, 120), "Momentum Gücü", fill=GRAY, font=font_small)
        draw.text((px, 150), f"%{m:.2f}", fill=GREEN, font=font_mid)

        draw.text((px, 190), "▰" * int(min(m * 5, 10)), fill=GREEN, font=font_mid)

        draw.text((px, 240), "VWAP Mesafe", fill=GRAY, font=font_small)
        draw.text((px, 270), f"%{v:.2f}", fill=YELLOW, font=font_mid)

        draw.text((px, 300), "▰" * int(min(v * 5, 10)), fill=YELLOW, font=font_mid)

        draw.text((px, 360), "DESTEK", fill=GRAY, font=font_small)
        draw.text((px, 390), str(data.get("support", "-")), fill=GREEN, font=font_mid)

        draw.text((px, 430), "DİRENÇ", fill=GRAY, font=font_small)
        draw.text((px, 460), str(data.get("resistance", "-")), fill=RED, font=font_mid)

        trend = data.get("trend", "YATAY")
        t_color = GREEN if trend == "YUKARI" else RED

        draw.text((px, 520), "TREND", fill=GRAY, font=font_small)
        draw.text((px, 550), trend, fill=t_color, font=get_font(28))

        decision = "RİSKLİ"
        color = RED

        if m > 1.2 and v < 1.5:
            decision = "GÜÇLÜ AL"
            color = GREEN
        elif m > 0.7:
            decision = "TREND BAŞLIYOR"
            color = YELLOW

        draw.text((px, 620), "KARAR", fill=GRAY, font=font_small)
        draw.text((px, 650), decision, fill=color, font=get_font(30))

        os.makedirs("cards", exist_ok=True)
        path = f"cards/{symbol}.png"
        img.save(path)

        return path

    except Exception as e:
        print("CARD ERROR:", e)
        return None
