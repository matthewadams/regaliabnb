#!/usr/bin/env python3
"""Render a Regalia 'Now Flying to Natchez' promo image from a queue JSON spec.
Usage: python3 tools/render_flight_promo.py <path-to-queue.json>
Writes flight-promo/<id>.png. Uses only fonts present in CI
(urw-base35 / lato / liberation / caladea / carlito) via a portable font finder.
"""
import sys, os, json, glob, math, random

from PIL import Image, ImageDraw, ImageFont, ImageFilter

S = 1080

def find_font(*names):
    roots = ['/usr/share/fonts', '/usr/local/share/fonts',
             os.path.expanduser('~/.fonts'), os.path.expanduser('~/Library/Fonts')]
    for n in names:
        for r in roots:
            hits = glob.glob(os.path.join(r, '**', n), recursive=True)
            if hits:
                return sorted(hits)[0]
    raise SystemExit('Font not found: ' + ' / '.join(names))

LATO_BLACK = find_font('Lato-Black.ttf')
LATO_BOLD  = find_font('Lato-Bold.ttf')
LATO_REG   = find_font('Lato-Regular.ttf')
MONO_B     = find_font('LiberationMono-Bold.ttf')
MONO_R     = find_font('LiberationMono-Regular.ttf')
PAL_B      = find_font('P052-Bold.otf')
PAL_I      = find_font('P052-Italic.otf')
PAL_BI     = find_font('P052-BoldItalic.otf')
PAL_R      = find_font('P052-Roman.otf')
CEN_B      = find_font('C059-Bold.otf')
CEN_I      = find_font('C059-Italic.otf')
CEN_BI     = find_font('C059-BdIta.otf')

def F(p, s): return ImageFont.truetype(p, s)
def tl(d, t, f): return d.textlength(t, font=f)
def ctext(d, cx, y, t, f, fill, ls=0):
    if ls:
        ws=[tl(d,c,f) for c in t]; tot=sum(ws)+ls*(len(t)-1); x=cx-tot/2
        for c,w in zip(t,ws): d.text((x,y),c,font=f,fill=fill); x+=w+ls
        return
    w=tl(d,t,f); d.text((cx-w/2,y),t,font=f,fill=fill)
def ltext(d,x,y,t,f,fill,ls=0):
    for c in t: d.text((x,y),c,font=f,fill=fill); x+=tl(d,c,f)+ls
    return x
def vgrad(size, top, bot):
    im=Image.new('RGB',(1,size[1]))
    for y in range(size[1]):
        t=y/size[1]; im.putpixel((0,y),tuple(int(top[i]+(bot[i]-top[i])*t) for i in range(3)))
    return im.resize(size)

def top_url_band(d, url, band, ink):
    d.rectangle([0,0,S,96], fill=band)
    ctext(d, S/2, 24, url, F(LATO_BLACK,44), ink)
    d.rectangle([0,96,S,101], fill=ink)

# ---- vibes ----
def boarding_pass(d, img, url, cta_sub):
    navy=(20,44,86); red=(198,54,44); ink=(40,54,74); grey=(140,152,170); paper=(255,255,255)
    top_url_band(d, url, navy, (238,214,150))
    m=70; top=210; bot=760; r=36
    d.rounded_rectangle([m,top,S-m,bot],radius=r,fill=paper)
    d.rounded_rectangle([m,top,S-m,top+84],radius=r,fill=navy); d.rectangle([m,top+48,S-m,top+84],fill=navy)
    ctext(d,S/2,top+22,"BOARDING PASS",F(LATO_BLACK,36),(255,255,255))
    px=690
    for yy in range(top+108,bot-16,32): d.ellipse([px-4,yy,px+4,yy+15],fill=(228,234,242))
    lx=m+44
    ltext(d,lx,top+120,"PASSENGER",F(LATO_BOLD,22),grey,ls=3)
    ltext(d,lx,top+152,"Regalia B&B Guest",F(LATO_BLACK,40),ink)
    ry=top+250
    ltext(d,lx,ry,"HOU",F(LATO_BLACK,88),navy)
    ax0=lx+214; ax1=lx+280; ay=ry+52
    d.line([ax0,ay,ax1,ay],fill=red,width=6); d.polygon([(ax1,ay-16),(ax1+24,ay),(ax1,ay+16),(ax1-4,ay)],fill=red)
    ltext(d,lx+320,ry,"HEZ",F(LATO_BLACK,88),red)
    ltext(d,lx+8,ry+112,"Houston",F(LATO_REG,24),grey); ltext(d,lx+330,ry+112,"Natchez, MS",F(LATO_REG,24),grey)
    iy=top+430
    for i,(k,v) in enumerate([("FLIGHT","UA 5139"),("SERVICE","Daily"),("NONSTOP","~80 min")]):
        cxx=lx+i*185; ltext(d,cxx,iy,k,F(LATO_BOLD,20),grey,ls=2); ltext(d,cxx,iy+30,v,F(LATO_BLACK,32),ink)
    sx=px+42
    ltext(d,sx,top+120,"NOW",F(LATO_BLACK,38),red); ltext(d,sx,top+164,"FLYING",F(LATO_BLACK,38),red)
    ltext(d,sx,top+224,"TO",F(LATO_BOLD,28),ink); ltext(d,sx,top+262,"NATCHEZ",F(LATO_BLACK,40),navy)
    ltext(d,sx,top+322,"HEZ",F(LATO_BLACK,56),red)
    random.seed(); bx=sx; by=bot-120; bh=80; xx=bx
    while xx<S-m-36:
        w=random.choice([3,3,6,9,4])
        if random.random()>0.35: d.rectangle([xx,by,xx+w,by+bh],fill=navy)
        xx+=w+3
    ctext(d,S/2,bot+30,cta_sub,F(LATO_BLACK,40),navy)
    ctext(d,S/2,bot+92,"Daily nonstop from Houston — Natchez has never been easier.",F(LATO_REG,26),ink)

def synthwave(d, img, url, cta_sub):
    mag=(255,44,180); cyan=(60,230,255); yel=(255,214,90); hor=560
    sun=vgrad((500,500),(255,120,40),(255,40,150)); mask=Image.new('L',(500,500),0)
    ImageDraw.Draw(mask).ellipse([0,0,500,500],fill=255); img.paste(sun,(S//2-250,hor-410),mask)
    d2=ImageDraw.Draw(img)
    for i,by in enumerate(range(hor-130,hor+120,26)): d2.rectangle([S//2-250,by,S//2+250,by+13-i],fill=(30,6,44))
    for gx in range(-10,11): d2.line([S/2+gx*22,hor,S/2+gx*90,S],fill=(150,40,140),width=2)
    yy=hor; step=8
    while yy<S: d2.line([0,yy,S,yy],fill=(150,40,140),width=2); step*=1.28; yy+=step
    for t,col,dx,dy in [("NOW FLYING",cyan,-5,-4),("NOW FLYING",mag,5,4),("NOW FLYING",(245,245,255),0,0)]: ctext(d2,S/2+dx,150+dy,t,F(LATO_BLACK,96),col)
    for t,col,dx,dy in [("TO NATCHEZ",cyan,-5,-4),("TO NATCHEZ",mag,5,4),("TO NATCHEZ",(245,245,255),0,0)]: ctext(d2,S/2+dx,262+dy,t,F(LATO_BLACK,96),col)
    ctext(d2,S/2,700,cta_sub.upper(),F(MONO_B,30),cyan,ls=1)
    ctext(d2,S/2,790,"DAILY NONSTOP FROM HOUSTON — ~80 MIN",F(MONO_R,24),yel,ls=2)
    ov=Image.new('RGBA',(S,S),(0,0,0,0)); od=ImageDraw.Draw(ov)
    for y in range(0,S,4): od.line([0,y,S,y],fill=(0,0,0,45),width=1)
    base=img.convert('RGBA'); base.alpha_composite(ov); img.paste(base.convert('RGB'),(0,0))
    top_url_band(ImageDraw.Draw(img), url, mag, (255,255,255))

def render(spec):
    vibe=spec.get('vibe','boarding_pass'); url=spec['url']; cta=spec.get('cta_sub','Come stay with us in Natchez!')
    if vibe=='synthwave':
        img=vgrad((S,S),(18,8,40),(60,12,80)).convert('RGB')
        synthwave(ImageDraw.Draw(img), img, url, cta)
    else:
        img=vgrad((S,S),(214,234,248),(163,201,232)).convert('RGB')
        d=ImageDraw.Draw(img)
        for cx,cy,r in [(150,150,80),(240,170,60),(900,240,70),(150,880,60)]:
            d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=(255,255,255))
        boarding_pass(d, img, url, cta)
    return img

if __name__=='__main__':
    qpath=sys.argv[1]
    spec=json.load(open(qpath))
    os.makedirs('flight-promo', exist_ok=True)
    img=render(spec)
    out=os.path.join('flight-promo', spec['id']+'.png')
    img.save(out)
    print('wrote', out)
