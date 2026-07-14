#!/usr/bin/env python3
"""Render a Regalia 'Now Flying to Natchez' promo image from a queue JSON spec.
Center-safe layout: URL, headline and CTA live in a crop-safe center band.
Usage: python3 tools/render_flight_promo.py <path-to-queue.json>
"""
import sys, os, json, glob, math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

S = 1080
def find_font(*names):
    roots = ['/usr/share/fonts', '/usr/local/share/fonts', os.path.expanduser('~/.fonts'), os.path.expanduser('~/Library/Fonts')]
    for n in names:
        for r in roots:
            hits = glob.glob(os.path.join(r, '**', n), recursive=True)
            if hits: return sorted(hits)[0]
    raise SystemExit('Font not found: ' + ' / '.join(names))
LATO_BLACK=find_font('Lato-Black.ttf'); LATO_BOLD=find_font('Lato-Bold.ttf'); LATO_REG=find_font('Lato-Regular.ttf')
MONO_B=find_font('LiberationMono-Bold.ttf'); MONO_R=find_font('LiberationMono-Regular.ttf')

def F(p,s): return ImageFont.truetype(p,s)
def tl(d,t,f): return d.textlength(t,font=f)
def ctext(d,cx,y,t,f,fill,ls=0):
    if ls:
        ws=[tl(d,c,f) for c in t]; tot=sum(ws)+ls*(len(t)-1); x=cx-tot/2
        for c,w in zip(t,ws): d.text((x,y),c,font=f,fill=fill); x+=w+ls
        return
    w=tl(d,t,f); d.text((cx-w/2,y),t,font=f,fill=fill)
def ltext(d,x,y,t,f,fill,ls=0):
    for c in t: d.text((x,y),c,font=f,fill=fill); x+=tl(d,c,f)+ls
    return x
def vgrad(size,top,bot):
    im=Image.new('RGB',(1,size[1]))
    for y in range(size[1]):
        t=y/size[1]; im.putpixel((0,y),tuple(int(top[i]+(bot[i]-top[i])*t) for i in range(3)))
    return im.resize(size)

def url_pill(d, cx, cy, url, fill, outline):
    uf=F(LATO_BLACK,46); uw=tl(d,url,uf)
    d.rounded_rectangle([cx-uw/2-40,cy-38,cx+uw/2+40,cy+42],radius=16,fill=fill,outline=outline,width=4)
    ctext(d,cx,cy-24,url,uf,(255,255,255))

def synthwave(d, img, url, cta_sub):
    mag=(255,44,180); cyan=(60,230,255)
    suncy=190
    sun=vgrad((420,420),(255,140,40),(255,40,150)); mask=Image.new('L',(420,420),0)
    ImageDraw.Draw(mask).ellipse([0,0,420,420],fill=255); img.paste(sun,(S//2-210,suncy-210),mask)
    d=ImageDraw.Draw(img)
    for i,by in enumerate(range(suncy-10,suncy+200,22)): d.rectangle([S//2-210,by,S//2+210,by+12-i],fill=(30,6,44))
    hor=780
    for gx in range(-10,11): d.line([S/2+gx*24,hor,S/2+gx*150,S],fill=(150,40,140),width=2)
    yy=hor; step=9
    while yy<S: d.line([0,yy,S,yy],fill=(150,40,140),width=2); step*=1.3; yy+=step
    for t,col,dx,dy in [("NOW FLYING",cyan,-5,-4),("NOW FLYING",mag,5,4),("NOW FLYING",(245,245,255),0,0)]: ctext(d,S/2+dx,410+dy,t,F(LATO_BLACK,90),col)
    for t,col,dx,dy in [("TO NATCHEZ",cyan,-5,-4),("TO NATCHEZ",mag,5,4),("TO NATCHEZ",(245,245,255),0,0)]: ctext(d,S/2+dx,510+dy,t,F(LATO_BLACK,90),col)
    url_pill(d,S/2,670,url,mag,cyan)
    ctext(d,S/2,730,cta_sub.upper(),F(MONO_B,26),cyan,ls=1)
    ov=Image.new('RGBA',(S,S),(0,0,0,0)); od=ImageDraw.Draw(ov)
    for y in range(0,S,4): od.line([0,y,S,y],fill=(0,0,0,45),width=1)
    base=img.convert('RGBA'); base.alpha_composite(ov); img.paste(base.convert('RGB'),(0,0))

def boarding_pass(d, img, url, cta_sub):
    navy=(20,44,86); red=(198,54,44); ink=(40,54,74); grey=(140,152,170); paper=(255,255,255)
    for cx,cy,r in [(150,150,80),(240,170,60),(900,240,70),(150,880,60)]: d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=(255,255,255))
    m=70; top=210; bot=760; r=36
    d.rounded_rectangle([m,top,S-m,bot],radius=r,fill=paper)
    d.rounded_rectangle([m,top,S-m,top+84],radius=r,fill=navy); d.rectangle([m,top+48,S-m,top+84],fill=navy)
    ctext(d,S/2,top+22,"BOARDING PASS",F(LATO_BLACK,36),(255,255,255))
    px=690
    for yy in range(top+108,bot-16,32): d.ellipse([px-4,yy,px+4,yy+15],fill=(228,234,242))
    lx=m+44
    ltext(d,lx,top+120,"PASSENGER",F(LATO_BOLD,22),grey,ls=3); ltext(d,lx,top+152,"Regalia B&B Guest",F(LATO_BLACK,40),ink)
    ry=top+250; ltext(d,lx,ry,"HOU",F(LATO_BLACK,88),navy)
    ax0=lx+214; ax1=lx+280; ay=ry+52
    d.line([ax0,ay,ax1,ay],fill=red,width=6); d.polygon([(ax1,ay-16),(ax1+24,ay),(ax1,ay+16),(ax1-4,ay)],fill=red)
    ltext(d,lx+320,ry,"HEZ",F(LATO_BLACK,88),red)
    ltext(d,lx+8,ry+112,"Houston",F(LATO_REG,24),grey); ltext(d,lx+330,ry+112,"Natchez, MS",F(LATO_REG,24),grey)
    iy=top+430
    for i,(k,v) in enumerate([("FLIGHT","UA 5139"),("SERVICE","Daily"),("NONSTOP","~80 min")]):
        cxx=lx+i*185; ltext(d,cxx,iy,k,F(LATO_BOLD,20),grey,ls=2); ltext(d,cxx,iy+30,v,F(LATO_BLACK,32),ink)
    sx=px+42
    ltext(d,sx,top+120,"NOW",F(LATO_BLACK,38),red); ltext(d,sx,top+164,"FLYING",F(LATO_BLACK,38),red)
    ltext(d,sx,top+224,"TO",F(LATO_BOLD,28),ink); ltext(d,sx,top+262,"NATCHEZ",F(LATO_BLACK,40),navy); ltext(d,sx,top+322,"HEZ",F(LATO_BLACK,56),red)
    random.seed(); xx=sx; by=bot-120
    while xx<S-m-36:
        w=random.choice([3,3,6,9,4])
        if random.random()>0.35: d.rectangle([xx,by,xx+w,by+80],fill=navy)
        xx+=w+3
    d.rounded_rectangle([S/2-260,bot+20,S/2+260,bot+92],radius=16,fill=navy)
    ctext(d,S/2,bot+34,url,F(LATO_BLACK,44),(238,214,150))
    ctext(d,S/2,bot+110,cta_sub,F(LATO_BOLD,30),ink)

def render(spec):
    vibe=spec.get('vibe','boarding_pass'); url=spec['url']; cta=spec.get('cta_sub','Come stay with us in Natchez!')
    if 'seed' in spec: random.seed(spec['seed'])
    if vibe=='synthwave':
        img=vgrad((S,S),(18,8,40),(60,12,80)).convert('RGB'); synthwave(ImageDraw.Draw(img), img, url, cta)
    else:
        img=vgrad((S,S),(214,234,248),(163,201,232)).convert('RGB'); boarding_pass(ImageDraw.Draw(img), img, url, cta)
    return img

if __name__=='__main__':
    spec=json.load(open(sys.argv[1])); os.makedirs('flight-promo', exist_ok=True)
    out=os.path.join('flight-promo', spec['id']+'.png'); render(spec).save(out); print('wrote', out)
