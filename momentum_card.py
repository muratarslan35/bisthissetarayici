from PIL import Image, ImageDraw, ImageFont
import os

WIDTH = 1000
HEIGHT = 600

BG = (8, 12, 20)
CARD = (15, 22, 35)

WHITE = (255, 255, 255)
GREEN = (0, 230, 140)
RED = (255, 80, 80)
YELLOW = (255, 190, 0)
BLUE = (0, 200, 255)
GRAY = (140, 150, 170)

# --------------------------------------------------
# SAFE FONT
# --------------------------------------------------

def get_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        try:
            return ImageFont.truetype("arial.ttf", size)
        except:
            return ImageFont.load_default()

# --------------------------------------------------
# BAR
# --------------------------------------------------

def build_bar(value, max_blocks=10):
    try:
        filled = int(min(value / 2, 1) * max_blocks)
        return "▰" * filled + "▱" * (max_blocks - filled)
    except:
        return "▱" * max_blocks

# --------------------------------------------------
# CANDLE CHART
# --------------------------------------------------

def draw_candles(draw, df, x, y, w, h):

    if df is None or len(df) < 5:
        return

    if not all(c in df.columns for c in ["open","close","high","low"]):
        return

    data = df.tail(30)

    highs = data["high"].max()
    lows = data["low"].min()

    if highs == lows:
        return

    def price_to_y(p):
        return y + h - (p - lows) / (highs - lows) * h

    candle_w = w / len(data)

    for i, (_, row) in enumerate(data.iterrows()):

        cx = x + i * candle_w + candle_w * 0.2

        o = row["open"]
        c = row["close"]
        hi = row["high"]
        lo = row["low"]

        color = GREEN if c >= o else RED

        draw.line(
            [cx + candle_w*0.3, price_to_y(hi),
             cx + candle_w*0.3, price_to_y(lo)],
            fill=color,
            width=1
        )

        draw.rectangle([
            cx,
            price_to_y(max(o, c)),
            cx + candle_w*0.6,
            price_to_y(min(o, c))
        ], fill=color)

# --------------------------------------------------
# MAIN CARD
# --------------------------------------------------

def build_momentum_card(data):

    try:
        if not data:
            return None

        symbol = str(data.get("symbol", "UNKNOWN"))

        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)

        # 🔥 FONTLAR (BÜYÜTÜLDÜ)
        font_big = get_font(40)
        font_mid = get_font(24)
        font_small = get_font(16)
        font_price = get_font(28)

        draw.rectangle([20, 20, WIDTH-20, HEIGHT-20], fill=CARD)

        # HEADER
        draw.text((40, 30), symbol, fill=WHITE, font=font_big)
        draw.text((650, 30), "MOMENTUM ANALİZ", fill=YELLOW, font=font_mid)

        # --------------------------------------------------
        # PRICES
        # --------------------------------------------------

        entry = float(data.get("entry", 0) or 0)
        live = float(data.get("live_price", 0) or 0)
        tp1 = float(data.get("tp1", 0) or 0)

        draw.text((40, 90), "Giriş", fill=GRAY, font=font_small)
        draw.text((40, 115), f"{round(entry,2)}", fill=WHITE, font=font_price)

        if live > 0:
            draw.text((200, 90), "Anlık", fill=GRAY, font=font_small)
            draw.text((200, 115), f"{round(live,2)}", fill=GREEN, font=font_price)

        if tp1 > 0:
            draw.text((360, 90), "TP1", fill=GRAY, font=font_small)
            draw.text((360, 115), f"{round(tp1,2)}", fill=BLUE, font=font_price)

        # --------------------------------------------------
        # CHART
        # --------------------------------------------------

        chart_x, chart_y = 40, 160
        chart_w, chart_h = 600, 320

        draw.rectangle(
            [chart_x, chart_y, chart_x+chart_w, chart_y+chart_h],
            outline=(50, 60, 80)
        )

        df = data.get("df15")

        if df is not None:

            df = df.dropna()

            if len(df) >= 10 and all(c in df.columns for c in ["open","close","high","low"]):

                draw_candles(draw, df, chart_x, chart_y, chart_w, chart_h)

                highs = max(df["high"].max(), tp1 if tp1 > 0 else df["high"].max())
                lows = df["low"].min()

                range_val = highs - lows if highs != lows else 1

                def get_y(price):
                    py = chart_y + chart_h - (price - lows) / range_val * chart_h
                    return max(chart_y, min(chart_y + chart_h, py))

                # LIVE LINE
                if live > 0:
                    py = get_y(live)

                    draw.line([chart_x, py, chart_x + chart_w], fill=YELLOW, width=1)
                    draw.text((chart_x + chart_w + 5, py - 10), f"{round(live,2)}", fill=YELLOW, font=font_small)

                # TP1 LINE
                if tp1 > 0:
                    py_tp = get_y(tp1)

                    draw.line([chart_x, py_tp, chart_x + chart_w], fill=BLUE, width=2)
                    draw.text((chart_x + chart_w + 5, py_tp - 10), f"TP1 {round(tp1,2)}", fill=BLUE, font=font_small)

        # --------------------------------------------------
        # RIGHT PANEL
        # --------------------------------------------------

        px = 700

        m = float(data.get("momentum", 0) or 0)
        v = float(data.get("vwap", 0) or 0)

        draw.text((px, 150), f"Momentum Gücü: %{round(m,2)}", fill=GREEN, font=font_mid)
        draw.text((px, 180), build_bar(m), fill=GREEN, font=font_mid)

        draw.text((px, 240), f"VWAP Mesafe: %{round(v,2)}", fill=YELLOW, font=font_mid)
        draw.text((px, 270), build_bar(v), fill=YELLOW, font=font_mid)

        # TP1 sağ panel
        if tp1 > 0:
            draw.text((px, 320), "TP1", fill=GRAY, font=font_small)
            draw.text((px, 345), f"{round(tp1,2)}", fill=BLUE, font=font_mid)

        # --------------------------------------------------
        # DECISION
        # --------------------------------------------------

        decision = "BEKLE"
        color = WHITE

        if m > 1.2 and v < 1.5:
            decision = "GÜÇLÜ AL"
            color = GREEN
        elif m > 0.7:
            decision = "TREND BAŞLIYOR"
            color = YELLOW
        else:
            decision = "RİSKLİ"
            color = RED

        draw.text((px, 400), "Karar:", fill=WHITE, font=font_mid)
        draw.text((px, 430), decision, fill=color, font=font_big)

        # --------------------------------------------------
        # SAVE
        # --------------------------------------------------

        os.makedirs("cards", exist_ok=True)
        path = f"cards/{symbol}.png"

        img.save(path)

        return path

    except Exception as e:
        print("CARD ERROR:", e)
        return None
