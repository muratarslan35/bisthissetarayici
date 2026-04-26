from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

WIDTH = 1200
HEIGHT = 800

# COLORS
BG_TOP = (10,15,25)
BG_BOTTOM = (5,10,18)

WHITE = (240,240,240)
GREEN = (0,255,160)
RED = (255,70,70)
YELLOW = (255,190,0)
BLUE = (0,200,255)
GRAY = (120,130,150)

# --------------------------------------------------
# FONT
# --------------------------------------------------
def get_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

# --------------------------------------------------
# GRADIENT BG
# --------------------------------------------------
def draw_bg(img):
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(BG_TOP[0]*(1-ratio) + BG_BOTTOM[0]*ratio)
        g = int(BG_TOP[1]*(1-ratio) + BG_BOTTOM[1]*ratio)
        b = int(BG_TOP[2]*(1-ratio) + BG_BOTTOM[2]*ratio)
        draw.line([(0,y),(WIDTH,y)], fill=(r,g,b))

# --------------------------------------------------
# GLOW LINE
# --------------------------------------------------
def glow_line(draw, pts, color):
    draw.line(pts, fill=color, width=4)
    draw.line(pts, fill=color, width=2)

# --------------------------------------------------
# SCALE
# --------------------------------------------------
def scale(df):
    return df["high"].max(), df["low"].min()

def py(p, high, low, y, h):
    return y + h - (p - low)/(high-low)*h

# --------------------------------------------------
# CANDLES
# --------------------------------------------------
def draw_candles(draw, df, x,y,w,h):

    df = df.tail(60)
    high, low = scale(df)
    cw = w/len(df)

    for i,row in enumerate(df.itertuples()):
        cx = x + i*cw
        o,c,hi,lo = row.open,row.close,row.high,row.low
        color = GREEN if c>=o else RED

        draw.line([
            cx+cw/3, py(hi,high,low,y,h),
            cx+cw/3, py(lo,high,low,y,h)
        ], fill=color, width=2)

        top = py(max(o,c),high,low,y,h)
        bot = py(min(o,c),high,low,y,h)

        if abs(top-bot)<1: bot=top+1

        draw.rectangle([cx,top,cx+cw*0.6,bot], fill=color)

# --------------------------------------------------
# EMA (SMOOTH)
# --------------------------------------------------
def draw_ema(draw, df, col, x,y,w,h,color):

    if col not in df.columns:
        return

    df = df.tail(60)
    high,low = scale(df)
    step = w/len(df)

    pts=[]
    for i,v in enumerate(df[col]):
        pts.append((x+i*step, py(v,high,low,y,h)))

    glow_line(draw, pts, color)

# --------------------------------------------------
# GRID
# --------------------------------------------------
def draw_grid(draw,x,y,w,h):
    for i in range(6):
        yy = y + i*(h/5)
        draw.line([x,yy,x+w,yy], fill=(30,40,60), width=1)

# --------------------------------------------------
# PRICE AXIS
# --------------------------------------------------
def draw_price_axis(draw, df, x,y,w,h):

    df = df.tail(60)
    high,low = scale(df)
    step=(high-low)/5

    for i in range(6):
        price = low + i*step
        yy = py(price,high,low,y,h)

        draw.text((x+w+10,yy-8),f"{price:.2f}",fill=GRAY,font=get_font(14))

# --------------------------------------------------
# CURRENT PRICE
# --------------------------------------------------
def draw_price_line(draw, price, df, x,y,w,h):

    high,low = scale(df)
    yy = py(price,high,low,y,h)

    draw.line([x,yy,x+w,yy], fill=GREEN, width=2)

    draw.rectangle([x+w+5,yy-10,x+w+75,yy+10], fill=GREEN)
    draw.text((x+w+8,yy-8),f"{price:.2f}",fill=(0,0,0),font=get_font(14))

# --------------------------------------------------
# PANEL BOX
# --------------------------------------------------
def panel(draw,x,y,w,h):
    draw.rectangle([x,y,x+w,y+h], fill=(15,20,30))

# --------------------------------------------------
# MAIN
# --------------------------------------------------
def build_momentum_card(data):

    img = Image.new("RGB",(WIDTH,HEIGHT))
    draw_bg(img)
    draw = ImageDraw.Draw(img)

    font_big = get_font(40)
    font_mid = get_font(20)
    font_small = get_font(14)

    symbol = data.get("symbol","")

    # HEADER
    draw.text((40,20),symbol,fill=WHITE,font=font_big)
    draw.text((400,30),"MOMENTUM ANALİZ",fill=YELLOW,font=font_mid)

    entry = float(data.get("entry",0))
    live = float(data.get("live_price",0))
    tp1 = float(data.get("tp1",0))

    # ---------------- GRAPH ----------------
    df15 = data.get("df15")

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
            yy = py(lvl,*scale(df15),y,h)
            draw.line([x,yy,x+w,yy], fill=color, width=2)

    # ---------------- RIGHT PANEL ----------------
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

    # DECISION
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

    # SAVE
    os.makedirs("cards",exist_ok=True)
    path=f"cards/{symbol}.png"
    img.save(path)

    return path
