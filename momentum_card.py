from PIL import Image, ImageDraw, ImageFont
import os

WIDTH = 1200
HEIGHT = 800

BG = (8, 12, 20)
GRID = (25, 35, 55)

WHITE = (255,255,255)
GREEN = (0,255,160)
RED = (255,70,70)
YELLOW = (255,190,0)
BLUE = (0,200,255)
GRAY = (130,140,160)

# --------------------------------------------------
# FONT
# --------------------------------------------------
def get_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def get_bounds(df):
    return df["high"].max(), df["low"].min()

def price_to_y(p, high, low, y, h):
    return y + h - (p - low) / (high - low) * h

# --------------------------------------------------
# GRID
# --------------------------------------------------
def draw_grid(draw, x, y, w, h):
    for i in range(6):
        yy = y + i * (h/5)
        draw.line([x,yy,x+w,yy], fill=GRID, width=1)

# --------------------------------------------------
# CANDLES
# --------------------------------------------------
def draw_candles(draw, df, x, y, w, h):

    if df is None or len(df) < 10:
        return

    df = df.tail(60)
    high, low = get_bounds(df)

    cw = w / len(df)

    for i, row in enumerate(df.itertuples()):

        cx = x + i * cw
        body_w = cw * 0.55

        o,c,hi,lo = row.open, row.close, row.high, row.low
        color = GREEN if c >= o else RED

        # wick
        draw.line([
            cx + body_w/2,
            price_to_y(hi,high,low,y,h),
            cx + body_w/2,
            price_to_y(lo,high,low,y,h)
        ], fill=color, width=2)

        # body
        top = price_to_y(max(o,c),high,low,y,h)
        bot = price_to_y(min(o,c),high,low,y,h)

        if abs(top - bot) < 1:
            bot = top + 1

        draw.rectangle([cx, top, cx+body_w, bot], fill=color)

# --------------------------------------------------
# EMA
# --------------------------------------------------
def draw_ema(draw, df, col, x, y, w, h, color):

    if df is None or col not in df.columns:
        return

    df = df.tail(60)
    high, low = get_bounds(df)
    step = w / len(df)

    pts = []

    for i, v in enumerate(df[col]):
        px = x + i * step
        py = price_to_y(v, high, low, y, h)
        pts.append((px, py))

    if len(pts) > 1:
        draw.line(pts, fill=color, width=3)

# --------------------------------------------------
# PRICE AXIS (SAĞDA FİYATLAR)
# --------------------------------------------------
def draw_price_axis(draw, df, x, y, w, h):

    if df is None or len(df) < 10:
        return

    df = df.tail(60)

    high = df["high"].max()
    low = df["low"].min()

    if high == low:
        return

    steps = 5
    step_val = (high - low) / steps

    for i in range(steps + 1):

        price = low + step_val * i
        py = y + h - (price - low) / (high - low) * h

        draw.text(
            (x + w + 10, py - 8),
            f"{price:.2f}",
            fill=(180,190,210),
            font=get_font(14)
        )

# --------------------------------------------------
# CURRENT PRICE LINE
# --------------------------------------------------
def draw_current_price(draw, price, df, x, y, w, h):

    if df is None or price is None:
        return

    high, low = get_bounds(df)

    if high == low:
        return

    py = price_to_y(price, high, low, y, h)

    draw.line([(x, py), (x + w, py)], fill=GREEN, width=2)

    # fiyat kutusu
    draw.rectangle([x + w + 5, py - 10, x + w + 70, py + 10], fill=GREEN)

    draw.text(
        (x + w + 8, py - 8),
        f"{price:.2f}",
        fill=(0,0,0),
        font=get_font(14)
    )

# --------------------------------------------------
# TIME AXIS
# --------------------------------------------------
def draw_time(draw, df, x, y, w):

    if df is None:
        return

    step = w / len(df)

    for i in range(0, len(df), 10):

        try:
            t = df.index[i]
            label = t.strftime("%H:%M")
            draw.text((x + i*step, y), label, fill=GRAY, font=get_font(11))
        except:
            pass

# --------------------------------------------------
# LEVEL LINES
# --------------------------------------------------
def draw_level(draw, price, df, x, y, w, h, color):

    if not price or df is None:
        return

    high, low = get_bounds(df)

    if high == low:
        return

    py = price_to_y(price, high, low, y, h)

    draw.line([x, py, x + w, py], fill=color, width=2)

# --------------------------------------------------
# VOLUME
# --------------------------------------------------
def draw_volume(draw, df, x, y, w, h):

    if df is None or len(df) < 10:
        return

    df = df.tail(60)
    maxv = df["volume"].max()

    if maxv == 0:
        return

    bw = w / len(df)

    for i, row in enumerate(df.itertuples()):

        v = row.volume
        o,c = row.open, row.close

        bh = (v / maxv) * h
        color = GREEN if c >= o else RED

        draw.rectangle([
            x + i*bw,
            y + h - bh,
            x + i*bw + bw*0.5,
            y + h
        ], fill=color)

# --------------------------------------------------
# MAIN CARD
# --------------------------------------------------
def build_momentum_card(data):

    img = Image.new("RGB",(WIDTH,HEIGHT),BG)
    draw = ImageDraw.Draw(img)

    font_big = get_font(40)
    font_mid = get_font(18)
    font_small = get_font(13)

    symbol = data.get("symbol","")

    # HEADER
    draw.text((40,20), symbol, fill=WHITE, font=font_big)
    draw.text((400,25),"MOMENTUM ANALİZ", fill=YELLOW, font=font_mid)

    entry = float(data.get("entry",0))
    live = float(data.get("live_price",0))
    tp1 = float(data.get("tp1",0))

    # RIGHT TOP
    px = 900

    draw.text((px,80),"GİRİŞ",fill=GRAY,font=font_small)
    draw.text((px,110),f"{entry:.2f}",fill=WHITE,font=get_font(26))

    draw.text((px+120,80),"ANLIK",fill=GRAY,font=font_small)
    draw.text((px+120,110),f"{live:.2f}",fill=GREEN,font=get_font(26))

    draw.text((px,150),"TP1",fill=GRAY,font=font_small)
    draw.text((px,180),f"{tp1:.2f}",fill=BLUE,font=get_font(22))

    # ---------------- 15M ----------------
    df15 = data.get("df15")

    x,y,w,h = 40,180,800,250

    draw_grid(draw,x,y,w,h)
    draw_candles(draw,df15,x,y,w,h)

    draw_ema(draw,df15,"ema20",x,y,w,h,BLUE)
    draw_ema(draw,df15,"ema50",x,y,w,h,YELLOW)

    draw_price_axis(draw,df15,x,y,w,h)
    draw_time(draw,df15,x,y+h+5,w)

    draw_level(draw,entry,df15,x,y,w,h,WHITE)
    draw_level(draw,data.get("support"),df15,x,y,w,h,GREEN)
    draw_level(draw,data.get("resistance"),df15,x,y,w,h,RED)

    draw_current_price(draw,live,df15,x,y,w,h)

    draw_volume(draw,df15,x,y+h+25,w,60)

    # ---------------- 1H ----------------
    df1h = data.get("df1h")

    if df1h is not None:

        x2,y2,w2,h2 = 40,500,800,200

        draw_grid(draw,x2,y2,w2,h2)
        draw_candles(draw,df1h,x2,y2,w2,h2)

        draw_ema(draw,df1h,"ema20",x2,y2,w2,h2,BLUE)
        draw_ema(draw,df1h,"ema50",x2,y2,w2,h2,YELLOW)

        draw_price_axis(draw,df1h,x2,y2,w2,h2)
        draw_time(draw,df1h,x2,y2+h2+5,w2)

        draw_current_price(draw,live,df1h,x2,y2,w2,h2)

    # ---------------- RIGHT PANEL ----------------
    m = float(data.get("momentum",0))
    v = float(data.get("vwap",0))

    draw.text((900,260),"Momentum",fill=GRAY,font=font_small)
    draw.text((900,290),f"%{m:.2f}",fill=GREEN,font=get_font(20))

    draw.text((900,330),"VWAP",fill=GRAY,font=font_small)
    draw.text((900,360),f"%{v:.2f}",fill=YELLOW,font=get_font(20))

    draw.text((900,420),"DESTEK",fill=GRAY,font=font_small)
    draw.text((900,450),f"{data.get('support','-')}",fill=GREEN,font=get_font(20))

    draw.text((900,490),"DİRENÇ",fill=GRAY,font=font_small)
    draw.text((900,520),f"{data.get('resistance','-')}",fill=RED,font=get_font(20))

    trend = data.get("trend","YATAY")
    tcolor = GREEN if trend == "YUKARI" else RED

    draw.text((900,580),"TREND",fill=GRAY,font=font_small)
    draw.text((900,610),trend,fill=tcolor,font=get_font(24))

    # ---------------- KARAR ----------------
    decision = "RİSKLİ"
    color = RED

    if m > 1.2 and v < 1.5:
        decision = "GÜÇLÜ AL"
        color = GREEN
    elif m > 0.7:
        decision = "TREND BAŞLIYOR"
        color = YELLOW

    draw.text((900,660),"KARAR",fill=GRAY,font=font_small)
    draw.text((900,690),decision,fill=color,font=get_font(28))

    desc = ""

    if decision == "GÜÇLÜ AL":
        desc = "Momentum güçlü, trend net."
    elif decision == "TREND BAŞLIYOR":
        desc = "Momentum artıyor, takip et."
    else:
        desc = "Zayıf yapı, dikkatli ol."

    draw.text((900,725),desc,fill=GRAY,font=get_font(14))

    # SAVE
    os.makedirs("cards",exist_ok=True)
    path = f"cards/{symbol}.png"
    img.save(path)

    return path
