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
        filled = int(min(max(value / 2, 0), 1) * max_blocks)
        return "▰" * filled + "▱" * (max_blocks - filled)
    except:
        return "▱" * max_blocks

# --------------------------------------------------
# CANDLE CHART
# --------------------------------------------------

def draw_candles(draw, df, x, y, w, h):

    try:
        if df is None or len(df) < 5:
            return

        if not all(c in df.columns for c in ["open","close","high","low"]):
            return

        data = df.tail(30)

        highs = data["high"].max()
        lows = data["low"].min()

        def price_to_y(p):
            return y + h - (p - lows) / (highs - lows + 1e-9) * h

        candle_w = w / len(data)

        for i, (_, row) in enumerate(data.iterrows()):

            cx = x + i * candle_w + candle_w * 0.2

            o = row["open"]
            c = row["close"]
            hi = row["high"]
            lo = row["low"]

            color = GREEN if c >= o else RED

            # wick
            draw.line(
                [cx + candle_w*0.3, price_to_y(hi),
                 cx + candle_w*0.3, price_to_y(lo)],
                fill=color,
                width=1
            )

            # body
            draw.rectangle([
                cx,
                price_to_y(max(o, c)),
                cx + candle_w*0.6,
                price_to_y(min(o, c))
            ], fill=color)

    except Exception as e:
        print("CANDLE ERROR:", e)

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

        font_big = get_font(36)
        font_mid = get_font(22)
        font_small = get_font(16)

        # CARD BG
        draw.rectangle([20, 20, WIDTH-20, HEIGHT-20], fill=CARD)

        # HEADER
        draw.text((40, 30), symbol, fill=WHITE, font=font_big)
        draw.text((650, 30), "MOMENTUM ANALİZ", fill=YELLOW, font=font_mid)

        # ENTRY + LIVE
        entry = float(data.get("entry", 0) or 0)
        live = float(data.get("live_price", 0) or 0)

        draw.text((40, 90), f"Giriş: {round(entry,2)}", fill=WHITE, font=font_mid)

        if live > 0:
            draw.text((220, 90), f"Anlık: {round(live,2)}", fill=GREEN, font=font_mid)

        # --------------------------------------------------
        # CHART AREA
        # --------------------------------------------------

        chart_x, chart_y = 40, 140
        chart_w, chart_h = 600, 300

        draw.rectangle(
            [chart_x, chart_y, chart_x+chart_w, chart_y+chart_h],
            outline=(50, 60, 80)
        )

        df = data.get("df15")

        if df is not None:

            # 🔥 TEMİZLE
            df = df.dropna()

            # 🔥 ZAYIF DATA BLOKLA
            if len(df) < 10:
                return

            if all(c in df.columns for c in ["open","close","high","low"]):

                draw_candles(draw, df, chart_x, chart_y, chart_w, chart_h)

            # LIVE PRICE LINE
            if live > 0:
                try:
                    highs = df["high"].max()
                    lows = df["low"].min()

                    py = chart_y + chart_h - (live - lows) / (highs - lows + 1e-9) * chart_h

                    draw.line(
                        [chart_x, py, chart_x + chart_w],
                        fill=YELLOW,
                        width=1
                    )

                    draw.text(
                        (chart_x + chart_w + 5, py - 10),
                        f"{round(live,2)}",
                        fill=YELLOW,
                        font=font_small
                    )
                except Exception as e:
                    print("LINE ERROR:", e)

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

        # --------------------------------------------------
        # DECISION ENGINE
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

        draw.text((px, 350), "Karar:", fill=WHITE, font=font_mid)
        draw.text((px, 380), decision, fill=color, font=font_big)

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
