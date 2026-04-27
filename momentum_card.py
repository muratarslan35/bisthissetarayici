from PIL import Image, ImageDraw, ImageFont
import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

WIDTH = 1200
HEIGHT = 900

TR = ZoneInfo("Europe/Istanbul")

# COLORS
BG_TOP = (10,15,25)
BG_BOTTOM = (5,10,18)

WHITE = (240,240,240)
GREEN = (0,255,160)
RED = (255,70,70)
YELLOW = (255,190,0)
BLUE = (0,200,255)
GRAY = (120,130,150)
GRID = (30,40,60)
BOX = (15,20,30)

# FONT
def get_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

# BG
def draw_bg(img):
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        r = int(BG_TOP[0]*(1-y/HEIGHT) + BG_BOTTOM[0]*(y/HEIGHT))
        g = int(BG_TOP[1]*(1-y/HEIGHT) + BG_BOTTOM[1]*(y/HEIGHT))
        b = int(BG_TOP[2]*(1-y/HEIGHT) + BG_BOTTOM[2]*(y/HEIGHT))
        draw.line([(0,y),(WIDTH,y)], fill=(r,g,b))

# VALID DF
def is_valid_df(df):
    try:
        return (
            df is not None
            and isinstance(df, pd.DataFrame)
            and len(df) > 20
            and all(c in df.columns for c in ["open","high","low","close"])
        )
    except:
        return False

# SCALE
def safe_scale(df):
    try:
        high = float(df["high"].max())
        low = float(df["low"].min())
        if high == low:
            high += 0.01
        return high, low
    except:
        return 1, 0

def py(p, high, low, y, h):
    return y + h - (p - low)/(high-low)*h

# GRID
def draw_grid(draw,x,y,w,h):
    for i in range(6):
        yy = y + i*(h/5)
        draw.line([x,yy,x+w,yy], fill=GRID, width=1)

# AXIS
def draw_price_axis(draw, df, x,y,w,h):
    high,low = safe_scale(df)
    step=(high-low)/5
    for i in range(6):
        price = low + i*step
        yy = py(price,high,low,y,h)
        draw.text((x+w+10,yy-8),f"{price:.2f}",fill=GRAY,font=get_font(13))

def draw_time_axis(draw, df, x,y,w,h):
    try:
        step = max(1, int(len(df)/6))
        for i in range(0,len(df),step):
            t = str(df.index[i])[-8:-3]
            xx = x + (i/len(df))*w
            draw.text((xx-15,y+h+5),t,fill=GRAY,font=get_font(11))
    except:
        pass

# CANDLES
def draw_candles(draw, df, x,y,w,h):
    high, low = safe_scale(df)
    cw = w/len(df)

    for i,row in enumerate(df.itertuples()):
        cx = x + i*cw
        o,c,hi,lo = row.open,row.close,row.high,row.low
        color = GREEN if c>=o else RED

        draw.line([cx+cw/2, py(hi,high,low,y,h),
                   cx+cw/2, py(lo,high,low,y,h)], fill=color, width=2)

        top = py(max(o,c),high,low,y,h)
        bot = py(min(o,c),high,low,y,h)
        if abs(top-bot)<1: bot=top+1

        draw.rectangle([cx,top,cx+cw*0.7,bot], fill=color)

# EMA
def draw_ema(draw, df, col, x,y,w,h,color):
    if col not in df.columns:
        return
    high,low = safe_scale(df)
    step = w/len(df)

    pts=[]
    for i,v in enumerate(df[col]):
        pts.append((x+i*step, py(v,high,low,y,h)))

    if len(pts)>1:
        draw.line(pts, fill=color, width=3)

# PRICE LINE
def draw_price_line(draw, price, df, x,y,w,h):
    high,low = safe_scale(df)
    yy = py(price,high,low,y,h)

    draw.line([x,yy,x+w,yy], fill=GREEN, width=2)
    draw.rectangle([x+w+5,yy-10,x+w+80,yy+10], fill=GREEN)
    draw.text((x+w+8,yy-8),f"{price:.2f}",fill=(0,0,0),font=get_font(13))

# FIBO
def draw_fibo(draw, df, x,y,w,h):
    try:
        high,low = safe_scale(df)

        fib_levels = [0.0,0.236,0.382,0.5,0.618,0.786,1.0]

        for lvl in fib_levels:
            price = high - (high-low)*lvl
            yy = py(price,high,low,y,h)

            draw.line([x,yy,x+w,yy], fill=(80,80,120), width=1)
            draw.text((x-55,yy-7),f"{lvl:.3f}",fill=GRAY,font=get_font(12))
    except:
        pass

# NO DATA
def draw_no_data(draw, x, y, w, h):
    msg = "Grafik Verisi Alınamadı"
    font = get_font(28)
    bbox = draw.textbbox((0,0), msg, font=font)
    tx = x + (w - (bbox[2]-bbox[0]))/2
    ty = y + (h - (bbox[3]-bbox[1]))/2
    draw.text((tx,ty), msg, fill=RED, font=font)

# LEGEND
def draw_legend(draw,x,y):
    draw.rectangle([x,y,x+160,y+40], fill=BOX)
    draw.rectangle([x+10,y+10,x+30,y+20], fill=BLUE)
    draw.text((x+35,y+5),"EMA20",fill=WHITE,font=get_font(13))
    draw.rectangle([x+10,y+25,x+30,y+35], fill=YELLOW)
    draw.text((x+35,y+20),"EMA50",fill=WHITE,font=get_font(13))

# PANEL
def panel(draw,x,y,w,h):
    draw.rectangle([x,y,x+w,y+h], fill=BOX)

# MAIN
def build_momentum_card(data):

    try:
        img = Image.new("RGB",(WIDTH,HEIGHT))
        draw_bg(img)
        draw = ImageDraw.Draw(img)

        symbol = data.get("symbol","")
        entry = float(data.get("entry",0))
        live = float(data.get("live_price",entry))
        tp1 = float(data.get("tp1",0))

        draw.text((40,20),symbol,fill=WHITE,font=get_font(42))
        draw.text((420,30),"MOMENTUM ANALİZ",fill=YELLOW,font=get_font(22))

        raw_df15 = data.get("df15")
        raw_df1h = data.get("df1h")

        valid15 = is_valid_df(raw_df15)
        valid1h = is_valid_df(raw_df1h)

        df15 = raw_df15.tail(120) if valid15 else None
        df1h = raw_df1h.tail(120) if valid1h else None

        # 15M
        x,y,w,h = 40,120,900,300
        draw.rectangle([x,y,x+w,y+h], outline=(60,80,100), width=2)

        if valid15:
            draw_grid(draw,x,y,w,h)
            draw_candles(draw,df15,x,y,w,h)
            draw_ema(draw,df15,"ema20",x,y,w,h,BLUE)
            draw_ema(draw,df15,"ema50",x,y,w,h,YELLOW)
            draw_fibo(draw,df15,x,y,w,h)
            draw_price_axis(draw,df15,x,y,w,h)
            draw_time_axis(draw,df15,x,y,w,h)
            draw_price_line(draw,live,df15,x,y,w,h)
        else:
            draw_no_data(draw,x,y,w,h)

        draw.text((x,y-20),"15 DK",fill=GREEN,font=get_font(14))

        # 1H
        y2 = 470
        h2 = 250
        draw.rectangle([x,y2,x+w,y2+h2], outline=(60,80,100), width=2)

        if valid1h:
            draw_grid(draw,x,y2,w,h2)
            draw_candles(draw,df1h,x,y2,w,h2)
            draw_ema(draw,df1h,"ema20",x,y2,w,h2,BLUE)
            draw_ema(draw,df1h,"ema50",x,y2,w,h2,YELLOW)
            draw_fibo(draw,df1h,x,y2,w,h2)
            draw_price_axis(draw,df1h,x,y2,w,h2)
            draw_time_axis(draw,df1h,x,y2,w,h2)
        else:
            draw_no_data(draw,x,y2,w,h2)

        draw.text((x,y2-20),"1 SAAT",fill=YELLOW,font=get_font(14))

        draw_legend(draw, x+10, y2+h2+20)

        # PANEL
        px = 960
        panel(draw,px,80,220,720)

        draw.text((px+10,100),"GİRİŞ",fill=GRAY,font=get_font(12))
        draw.text((px+10,120),f"{entry:.2f}",fill=WHITE,font=get_font(20))

        draw.text((px+10,160),"ANLIK",fill=GRAY,font=get_font(12))
        draw.text((px+10,180),f"{live:.2f}",fill=GREEN,font=get_font(20))

        draw.text((px+10,220),"TP1",fill=GRAY,font=get_font(12))
        draw.text((px+10,240),f"{tp1:.2f}",fill=BLUE,font=get_font(18))

        m = float(data.get("momentum",0))
        v = float(data.get("vwap",0))

        draw.text((px+10,300),"Momentum",fill=GRAY,font=get_font(12))
        draw.text((px+10,320),f"%{m:.2f}",fill=GREEN,font=get_font(16))

        draw.text((px+10,360),"VWAP",fill=GRAY,font=get_font(12))
        draw.text((px+10,380),f"%{v:.2f}",fill=YELLOW,font=get_font(16))

        trend = data.get("trend","YATAY")
        tcol = GREEN if trend=="YUKARI" else RED

        draw.text((px+10,440),"TREND",fill=GRAY,font=get_font(12))
        draw.text((px+10,460),trend,fill=tcol,font=get_font(18))

        decision="RİSKLİ"
        col=RED
        if m>1.2 and v<1.5:
            decision="GÜÇLÜ AL"
            col=GREEN
        elif m>0.7:
            decision="TREND BAŞLIYOR"
            col=YELLOW

        draw.text((px+10,520),"KARAR",fill=GRAY,font=get_font(12))
        draw.text((px+10,540),decision,fill=col,font=get_font(20))

        now = datetime.now(TR)
        draw.text((40,860),now.strftime("%d.%m.%Y %H:%M"),fill=GRAY,font=get_font(14))

        os.makedirs("cards",exist_ok=True)
        path=f"cards/{symbol}.png"
        img.save(path)

        return path

    except Exception as e:
        print("CARD ERROR:", e)
        return None
