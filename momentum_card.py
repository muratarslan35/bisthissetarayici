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
