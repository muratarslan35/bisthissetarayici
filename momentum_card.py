from PIL import Image, ImageDraw, ImageFont
import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

WIDTH = 1200
HEIGHT = 800

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

# SAFE SCALE
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

# SAFE DF
def ensure_df(df, fallback_price):
    if df is None or len(df) < 5:
        return pd.DataFrame({
            "open":[fallback_price]*30,
            "high":[fallback_price]*30,
            "low":[fallback_price]*30,
            "close":[fallback_price]*30,
            "volume":[1]*30
        })
    return df.tail(60)

# CANDLES
def draw_candles(draw, df, x,y,w,h):
    try:
        df = df.tail(60)
        high, low = safe_scale(df)
        cw = w/len(df)

        for i,row in enumerate(df.itertuples()):
            cx = x + i*cw
            o,c,hi,lo = row.open,row.close,row.high,row.low
            color = GREEN if c>=o else RED

            draw.line([cx+cw/3, py(hi,high,low,y,h),
                       cx+cw/3, py(lo,high,low,y,h)], fill=color, width=2)

            top = py(max(o,c),high,low,y,h)
            bot = py(min(o,c),high,low,y,h)
            if abs(top-bot)<1: bot=top+1

            draw.rectangle([cx,top,cx+cw*0.6,bot], fill=color)
    except:
        pass

# EMA
def draw_ema(draw, df, col, x,y,w,h,color):
    try:
        if col not in df.columns:
            return
        df = df.tail(60)
        high,low = safe_scale(df)
        step = w/len(df)

        pts=[]
        for i,v in enumerate(df[col]):
            pts.append((x+i*step, py(v,high,low,y,h)))

        if len(pts)>1:
            draw.line(pts, fill=color, width=3)
    except:
        pass

# GRID
def draw_grid(draw,x,y,w,h):
    for i in range(6):
        yy = y + i*(h/5)
        draw.line([x,yy,x+w,yy], fill=(30,40,60), width=1)

# PRICE AXIS
def draw_price_axis(draw, df, x,y,w,h):
    try:
        high,low = safe_scale(df)
        step=(high-low)/5

        for i in range(6):
            price = low + i*step
            yy = py(price,high,low,y,h)
            draw.text((x+w+10,yy-8),f"{price:.2f}",fill=GRAY,font=get_font(14))
    except:
        pass

# PRICE LINE
def draw_price_line(draw, price, df, x,y,w,h):
    try:
        high,low = safe_scale(df)
        yy = py(price,high,low,y,h)

        draw.line([x,yy,x+w,yy], fill=GREEN, width=2)
        draw.rectangle([x+w+5,yy-10,x+w+75,yy+10], fill=GREEN)
        draw.text((x+w+8,yy-8),f"{price:.2f}",fill=(0,0,0),font=get_font(14))
    except:
        pass

# PANEL
def panel(draw,x,y,w,h):
    draw.rectangle([x,y,x+w,y+h], fill=(15,20,30))

# ==================================================
# MAIN (CRASH SAFE)
# ==================================================
def build_momentum_card(data):

    try:
        img = Image.new("RGB",(WIDTH,HEIGHT))
        draw_bg(img)
        draw = ImageDraw.Draw(img)

        font_big = get_font(40)
        font_mid = get_font(20)
        font_small = get_font(14)

        symbol = data.get("symbol","")

        entry = float(data.get("entry",0))
        live = float(data.get("live_price",entry))
        tp1 = float(data.get("tp1",0))

        # HEADER
        draw.text((40,20),symbol,fill=WHITE,font=font_big)
        draw.text((400,30),"MOMENTUM ANALİZ",fill=YELLOW,font=font_mid)

        # SAFE DF
        df15 = ensure_df(data.get("df15"), entry)

        # GRAPH
        x,y,w,h = 40,150,800,260

        draw_grid(draw,x,y,w,h)
        draw_candles(draw,df15,x,y,w,h)
        draw_ema(draw,df15,"ema20",x,y,w,h,BLUE)
        draw_ema(draw,df15,"ema50",x,y,w,h,YELLOW)

        draw_price_axis(draw,df15,x,y,w,h)
        draw_price_line(draw,live,df15,x,y,w,h)

        # LEVELS
        for lvl,color in [
            (entry,WHITE),
            (data.get("support"),GREEN),
            (data.get("resistance"),RED)
        ]:
            if lvl:
                try:
                    yy = py(lvl,*safe_scale(df15),y,h)
                    draw.line([x,yy,x+w,yy], fill=color, width=2)
                except:
                    pass

        # RIGHT PANEL
        px = 880
        panel(draw,px,80,280,650)

        draw.text((px+20,100),"GİRİŞ",fill=GRAY,font=font_small)
        draw.text((px+20,130),f"{entry:.2f}",fill=WHITE,font=get_font(26))

        draw.text((px+150,100),"ANLIK",fill=GRAY,font=font_small)
        draw.text((px+150,130),f"{live:.2f}",fill=GREEN,font=get_font(26))

        draw.text((px+20,170),"TP1",fill=GRAY,font=font_small)
        draw.text((px+20,200),f"{tp1:.2f}",fill=BLUE,font=get_font(22))

        m = float(data.get("momentum",0))
        v = float(data.get("vwap",0))

        draw.text((px+20,260),"Momentum",fill=GRAY,font=font_small)
        draw.text((px+20,290),f"%{m:.2f}",fill=GREEN,font=font_mid)

        draw.text((px+20,330),"VWAP",fill=GRAY,font=font_small)
        draw.text((px+20,360),f"%{v:.2f}",fill=YELLOW,font=font_mid)

        draw.text((px+20,420),"DESTEK",fill=GRAY,font=font_small)
        draw.text((px+20,450),str(data.get("support","-")),fill=GREEN,font=font_mid)

        draw.text((px+20,490),"DİRENÇ",fill=GRAY,font=font_small)
        draw.text((px+20,520),str(data.get("resistance","-")),fill=RED,font=font_mid)

        trend = data.get("trend","YATAY")
        tcol = GREEN if trend=="YUKARI" else RED

        draw.text((px+20,580),"TREND",fill=GRAY,font=font_small)
        draw.text((px+20,610),trend,fill=tcol,font=get_font(24))

        decision="RİSKLİ"
        col=RED
        if m>1.2 and v<1.5:
            decision="GÜÇLÜ AL"
            col=GREEN
        elif m>0.7:
            decision="TREND BAŞLIYOR"
            col=YELLOW

        draw.text((px+20,650),"KARAR",fill=GRAY,font=font_small)
        draw.text((px+20,680),decision,fill=col,font=get_font(28))

        # TIME FIX
        now = datetime.now(TR)
        draw.text((40,740),now.strftime("%d.%m.%Y %H:%M"),fill=GRAY,font=get_font(14))

        os.makedirs("cards",exist_ok=True)
        path=f"cards/{symbol}.png"
        img.save(path)

        return path

    except Exception as e:
        print("CARD ERROR:", e)
        return None
