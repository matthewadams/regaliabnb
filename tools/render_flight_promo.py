#!/usr/bin/env python3
"""Regalia 'Now Flying to Natchez' promo renderer. Center-safe: URL, headline and
CTA live inside a crop-safe center band (y~300-780) so nothing is clipped by
Buffer thumbnails, Instagram, Facebook, or vertical TikTok. Decorative art bleeds
to the edges. CI-safe fonts (urw-base35/lato/liberation/caladea/carlito).
Usage: python3 tools/render_flight_promo.py <queue.json>  ->  flight-promo/<id>.png
"""
import sys, os, json, glob, math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
S=1080
def find_font(*names):
    roots=['/usr/share/fonts','/usr/local/share/fonts',os.path.expanduser('~/.fonts'),os.path.expanduser('~/Library/Fonts')]
    for n in names:
        for r in roots:
            h=glob.glob(os.path.join(r,'**',n),recursive=True)
            if h: return sorted(h)[0]
    raise SystemExit('Font not found: '+' / '.join(names))
LATO_BLACK=find_font('Lato-Black.ttf'); LATO_BOLD=find_font('Lato-Bold.ttf'); LATO_REG=find_font('Lato-Regular.ttf')
MONO_B=find_font('LiberationMono-Bold.ttf'); MONO_R=find_font('LiberationMono-Regular.ttf')
PAL_B=find_font('P052-Bold.otf'); PAL_I=find_font('P052-Italic.otf'); PAL_BI=find_font('P052-BoldItalic.otf'); PAL_R=find_font('P052-Roman.otf')
CEN_B=find_font('C059-Bold.otf'); CEN_I=find_font('C059-Italic.otf'); CEN_BI=find_font('C059-BdIta.otf')
def find_font_opt(*names):
    try: return find_font(*names)
    except SystemExit: return None
DEJA=find_font_opt('DejaVuSans.ttf')  # clean airplane glyph U+2708 (add fonts-dejavu-core in CI)
def glyph_plane(size,color,ang):
    if not DEJA: return None
    f=F(DEJA,size); tmp=Image.new('RGBA',(int(size*1.6),int(size*1.6)),(0,0,0,0)); td=ImageDraw.Draw(tmp)
    bb=td.textbbox((0,0),'✈',font=f)
    td.text(((tmp.width-(bb[2]-bb[0]))/2-bb[0],(tmp.height-(bb[3]-bb[1]))/2-bb[1]),'✈',font=f,fill=color)
    return tmp.rotate(ang,expand=True,resample=Image.BICUBIC)
def paste_c(img,pl,cx,cy):
    img.paste(pl,(int(cx-pl.width/2),int(cy-pl.height/2)),pl)
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
def fit(d,t,path,maxw,s0):
    s=s0
    while tl(d,t,F(path,s))>maxw and s>14: s-=1
    return F(path,s)
def url_pill(d,cx,cy,url,fill,txt,outline=None):
    uf=F(LATO_BLACK,44); uw=tl(d,url,uf)
    box=[cx-uw/2-38,cy-36,cx+uw/2+38,cy+40]
    d.rounded_rectangle(box,radius=16,fill=fill,outline=outline,width=4 if outline else 0)
    ctext(d,cx,cy-22,url,uf,txt)

EASE="Daily nonstop from Houston — about 80 minutes."

# ---- 1 synthwave (approved v2) ----
def synthwave(img,url,cta):
    mag=(255,44,180); cyan=(60,230,255); suncy=190
    sun=vgrad((420,420),(255,140,40),(255,40,150)); mask=Image.new('L',(420,420),0)
    ImageDraw.Draw(mask).ellipse([0,0,420,420],fill=255); img.paste(sun,(S//2-210,suncy-210),mask); d=ImageDraw.Draw(img)
    for i,by in enumerate(range(suncy-10,suncy+200,22)): d.rectangle([S//2-210,by,S//2+210,by+12-i],fill=(30,6,44))
    hor=800
    for gx in range(-10,11): d.line([S/2+gx*24,hor,S/2+gx*150,S],fill=(150,40,140),width=2)
    yy=hor; step=9
    while yy<S: d.line([0,yy,S,yy],fill=(150,40,140),width=2); step*=1.3; yy+=step
    for t,c,dx,dy in [("NOW FLYING",cyan,-5,-4),("NOW FLYING",mag,5,4),("NOW FLYING",(245,245,255),0,0)]: ctext(d,S/2+dx,400+dy,t,F(LATO_BLACK,88),c)
    for t,c,dx,dy in [("TO NATCHEZ",cyan,-5,-4),("TO NATCHEZ",mag,5,4),("TO NATCHEZ",(245,245,255),0,0)]: ctext(d,S/2+dx,498+dy,t,F(LATO_BLACK,88),c)
    url_pill(d,S/2,650,url,mag,(255,255,255),cyan); ctext(d,S/2,712,cta.upper(),F(MONO_B,26),cyan,ls=1)
    ov=Image.new('RGBA',(S,S),(0,0,0,0)); od=ImageDraw.Draw(ov)
    for y in range(0,S,4): od.line([0,y,S,y],fill=(0,0,0,45),width=1)
    b=img.convert('RGBA'); b.alpha_composite(ov); img.paste(b.convert('RGB'),(0,0))

# ---- 2 boarding pass ----
def boarding_pass(img,url,cta):
    d=ImageDraw.Draw(img)
    for cx,cy,r in [(140,150,80),(230,170,60),(920,180,70),(150,930,64),(950,940,70)]: d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=(255,255,255))
    navy=(20,44,86); red=(198,54,44); ink=(40,54,74); grey=(140,152,170)
    m=80; top=250; bot=720
    d.rounded_rectangle([m,top,S-m,bot],radius=34,fill=(255,255,255))
    d.rounded_rectangle([m,top,S-m,top+92],radius=34,fill=navy); d.rectangle([m,top+52,S-m,top+92],fill=navy)
    ctext(d,S/2,top+24,url,F(LATO_BLACK,46),(238,214,150))
    px=690
    for yy in range(top+116,bot-16,32): d.ellipse([px-4,yy,px+4,yy+15],fill=(228,234,242))
    lx=m+40
    ltext(d,lx,top+120,"PASSENGER",F(LATO_BOLD,20),grey,ls=3); ltext(d,lx,top+150,"Regalia B&B Guest",F(LATO_BLACK,38),ink)
    ry=top+232; ltext(d,lx,ry,"HOU",F(LATO_BLACK,82),navy)
    ax0=lx+200; ax1=lx+262; ay=ry+48
    d.line([ax0,ay,ax1,ay],fill=red,width=6); d.polygon([(ax1,ay-15),(ax1+22,ay),(ax1,ay+15),(ax1-4,ay)],fill=red)
    ltext(d,lx+300,ry,"HEZ",F(LATO_BLACK,82),red)
    ltext(d,lx+6,ry+104,"Houston",F(LATO_REG,22),grey); ltext(d,lx+306,ry+104,"Natchez, MS",F(LATO_REG,22),grey)
    iy=top+372
    for i,(k,v) in enumerate([("FLIGHT","UA 5139"),("SERVICE","Daily"),("NONSTOP","~80 min")]):
        cxx=lx+i*172; ltext(d,cxx,iy,k,F(LATO_BOLD,18),grey,ls=2); ltext(d,cxx,iy+28,v,F(LATO_BLACK,30),ink)
    sx=px+40
    ltext(d,sx,top+116,"NOW",F(LATO_BLACK,34),red); ltext(d,sx,top+156,"FLYING",F(LATO_BLACK,34),red)
    ltext(d,sx,top+210,"TO",F(LATO_BOLD,26),ink); ltext(d,sx,top+244,"NATCHEZ",F(LATO_BLACK,34),navy); ltext(d,sx,top+296,"HEZ",F(LATO_BLACK,50),red)
    random.seed(); xx=sx; by=bot-96
    while xx<S-m-32:
        w=random.choice([3,3,6,9,4])
        if random.random()>0.35: d.rectangle([xx,by,xx+w,by+62],fill=navy)
        xx+=w+3
    cf=fit(d,cta,LATO_BLACK,S-260,40); ctext(d,S/2,bot+34,cta,cf,navy)

# ---- 3 departure board ----
def departure(img,url,cta):
    d=ImageDraw.Draw(img)
    amber=(255,187,64); white=(238,240,245); dim=(150,158,172); green=(88,214,141)
    ctext(d,S/2,150,"NOW FLYING TO NATCHEZ",F(LATO_BLACK,54),white)
    d.rounded_rectangle([80,240,S-80,700],radius=22,fill=(22,25,33),outline=(44,50,64),width=3)
    cols=[120,320,620,830]; hy=272
    for x,t in zip(cols,["FLIGHT","FROM","GATE","STATUS"]): ltext(d,x,hy,t,F(MONO_B,22),dim,ls=1)
    d.line([110,hy+42,S-110,hy+42],fill=(44,50,64),width=2)
    rows=[("UA 5139","HOUSTON IAH","A1","LANDED",green),("UA 5086","NATCHEZ HEZ","A1","BOARDING",amber),("REGALIA","YOUR STAY","BNB","BOOK NOW",amber)]
    ry=hy+74
    for fl,frm,gt,st,col in rows:
        ltext(d,cols[0],ry,fl,F(MONO_B,26),white); ltext(d,cols[1],ry,frm,F(MONO_B,26),white); ltext(d,cols[2],ry,gt,F(MONO_B,26),white)
        pw=tl(d,st,F(MONO_B,24)); d.rounded_rectangle([cols[3]-8,ry-6,cols[3]+pw+14,ry+38],radius=8,fill=(34,40,52)); ltext(d,cols[3]+2,ry,st,F(MONO_B,24),col)
        ry+=92
    url_pill(d,S/2,748,url,amber,(20,20,24)); ctext(d,S/2,806,cta,F(MONO_R,24),dim,ls=1)

# ---- 4 sky ----
def sky(img,url,cta):
    cl=Image.new('L',(S,S),0); dc=ImageDraw.Draw(cl)
    for cx,cy,rw,rh in [(220,880,280,90),(320,940,320,120),(840,930,320,120),(910,220,150,60),(170,250,150,55)]: dc.ellipse([cx-rw,cy-rh,cx+rw,cy+rh],fill=200)
    cl=cl.filter(ImageFilter.GaussianBlur(30)); img.paste(Image.composite(Image.new('RGB',(S,S),(255,255,255)),img.copy(),cl),(0,0)); d=ImageDraw.Draw(img)
    navy=(24,46,88); red=(206,58,46)
    for i in range(40):
        t=i/40; x=170+t*560; y=250-t*150; rr=int(18*(1-t))+3; d.ellipse([x-rr,y-rr,x+rr,y+rr],fill=(255,255,255))
    pl=glyph_plane(150,navy,35)
    if pl: paste_c(img,pl,720,90); d=ImageDraw.Draw(img)
    ctext(d,S/2,330,"NOW FLYING",F(LATO_BLACK,96),navy); ctext(d,S/2,438,"TO NATCHEZ",F(LATO_BLACK,96),red)
    url_pill(d,S/2,590,url,navy,(255,255,255))
    cf=fit(d,cta,LATO_BOLD,S-260,34); ctext(d,S/2,672,cta,cf,navy)
    d.rounded_rectangle([S/2-120,724,S/2+120,772],radius=12,fill=navy); ctext(d,S/2,732,"HEZ · NATCHEZ, MS",F(LATO_BOLD,22),(255,255,255))

# ---- 5 jetsons ----
def jetsons(img,url,cta):
    cream=(244,237,220); teal=(38,178,168); coral=(240,96,66); mustard=(244,192,64); ink=(40,40,52)
    d=ImageDraw.Draw(img)
    d.arc([120,-260,760,300],start=20,end=140,fill=coral,width=44)
    ox,oy=968,150
    for ang in (0,60,120):
        e=Image.new('RGBA',(280,280),(0,0,0,0)); ed=ImageDraw.Draw(e); ed.ellipse([22,110,258,170],outline=ink+(255,),width=6); e=e.rotate(ang,center=(140,140)); img.paste(e,(ox-140,oy-140),e)
    d=ImageDraw.Draw(img); d.ellipse([ox-15,oy-15,ox+15,oy+15],fill=coral)
    sx,sy=150,930
    for a in range(0,360,15):
        L=60 if (a//15)%2==0 else 34; d.line([sx,sy,sx+math.cos(math.radians(a))*L,sy+math.sin(math.radians(a))*L],fill=mustard,width=6)
    cx,cy=900,900; d.ellipse([cx-140,cy-28,cx+140,cy+28],fill=teal); d.ellipse([cx-64,cy-64,cx+64,cy+4],fill=coral)
    for k in (-80,-34,12,58): d.ellipse([cx+k-7,cy-3,cx+k+7,cy+11],fill=cream)
    ctext(d,S/2,300,"THE FUTURE HAS LANDED",F(LATO_BLACK,32),coral,ls=3)
    ctext(d,S/2,360,"NOW FLYING",F(LATO_BLACK,100),ink); ctext(d,S/2,470,"TO NATCHEZ",F(LATO_BLACK,100),teal)
    url_pill(d,S/2,620,url,ink,cream); cf=fit(d,cta,LATO_BOLD,S-280,38); ctext(d,S/2,700,cta,cf,ink)

# ---- 6 nagel ----
def nagel(img,url,cta):
    teal=(46,150,148); cream=(238,229,214); black=(24,22,26); pink=(232,74,120); skin=(238,224,214); red=(200,40,60)
    d=ImageDraw.Draw(img); d.rectangle([0,0,S,S],fill=teal); d.rectangle([0,0,110,S],fill=black); d.rectangle([110,0,160,S],fill=pink)
    fx,fy=820,60
    d.polygon([(fx-30,fy),(fx+180,fy),(fx+180,470),(fx-70,470),(fx-95,300),(fx-55,180),(fx-30,120)],fill=skin)
    d.polygon([(fx-40,fy),(fx+230,fy),(fx+230,250),(fx+120,220),(fx+96,150),(fx+30,150),(fx-10,250),(fx-60,250)],fill=black)
    for cxx in (fx+40,fx+150): d.ellipse([cxx-44,250,cxx+44,326],fill=black)
    d.rectangle([fx+84,272,fx+106,286],fill=black)
    d.ellipse([fx+58,392,fx+142,426],fill=red)
    ctext(d,S/2-40,340,"NOW FLYING",F(LATO_BLACK,72),cream); ctext(d,S/2-40,420,"TO NATCHEZ",F(LATO_BLACK,72),pink)
    url_pill(d,S/2-40,560,url,black,cream); cf=fit(d,cta,LATO_BOLD,620,34); ctext(d,S/2-40,650,cta,cf,cream)

# ---- 7 ransom ----
def ransom(img,url,cta):
    random.seed(); bg=(223,219,208); d=ImageDraw.Draw(img); d.rectangle([0,0,S,S],fill=bg)
    for cx in range(40,S,150):
        for ln in range(60,S-40,18):
            if random.random()>0.3: d.line([cx,ln,cx+110*random.random(),ln],fill=(205,201,190),width=2)
    fonts=[LATO_BLACK,MONO_B,PAL_B,CEN_B,LATO_REG,CEN_BI]; papers=[(250,248,240),(20,20,24),(232,70,70),(60,120,210),(245,210,60),(250,250,250),(40,150,140)]
    def tile(ch,fs):
        f=F(random.choice(fonts),fs); pw=int(tl(ImageDraw.Draw(Image.new('RGB',(2,2))),ch,f))+random.randint(12,22); ph=int(fs*1.5)
        paper=random.choice(papers); til=Image.new('RGBA',(pw,ph),(0,0,0,0)); td=ImageDraw.Draw(til); td.rectangle([0,0,pw,ph],fill=paper+(255,))
        fg=(245,245,245) if sum(paper)<300 else (20,20,24); td.text(((pw-tl(td,ch,f))/2,(ph-fs*1.25)/2),ch,font=f,fill=fg)
        return til.rotate(random.uniform(-10,10),expand=True,resample=Image.BICUBIC)
    def word(line,fs,cy):
        tiles=[tile(c,fs) for c in line]; gap=6; total=sum(t.width for t in tiles)+gap*(len(tiles)-1); x=(S-total)//2
        for t in tiles: img.paste(t,(x,int(cy-t.height/2+random.randint(-7,7))),t); x+=t.width+gap
    word("NOW FLYING",78,330); word("TO NATCHEZ",78,450)
    d=ImageDraw.Draw(img); uf=F(MONO_B,40); uw=tl(d,url,uf)
    d.rectangle([S/2-uw/2-24,568,S/2+uw/2+24,636],fill=(20,20,24)); ctext(d,S/2,580,url,uf,(245,210,60))
    d.rectangle([S/2-tl(d,cta,F(MONO_R,26))/2-16,676,S/2+tl(d,cta,F(MONO_R,26))/2+16,724],fill=(232,70,70)); ctext(d,S/2,684,cta,F(MONO_R,26),(255,255,255))

# ---- 8 victorian ----
def victorian(img,url,cta):
    burg=(110,34,51); gold=(176,135,59); ink=(43,32,22)
    img.paste(vgrad((S,S),(247,239,221),(233,220,196)).convert('RGB'),(0,0)); d=ImageDraw.Draw(img)
    d.rectangle([46,150,S-46,930],outline=burg,width=4); d.rectangle([60,164,S-60,916],outline=gold,width=2)
    for (x,y,fx,fy) in [(92,196,1,1),(S-92,196,-1,1),(92,884,1,-1),(S-92,884,-1,-1)]:
        d.line([x,y,x+fx*64,y],fill=gold,width=4); d.line([x,y,x,y+fy*64],fill=gold,width=4)
        d.ellipse([x+fx*64-6,y-6,x+fx*64+6,y+6],fill=gold); d.ellipse([x-6,y+fy*64-6,x+6,y+fy*64+6],fill=gold)
    ctext(d,S/2,220,"NOW ARRIVING IN",F(PAL_R,30),burg,ls=6); ctext(d,S/2,262,"Natchez, Mississippi",F(PAL_BI,46),ink)
    pl=glyph_plane(118,burg,45)
    if pl:
        paste_c(img,pl,S/2,372); d=ImageDraw.Draw(img)
    else:
        d.line([S/2-160,372,S/2-24,372],fill=gold,width=3); d.line([S/2+24,372,S/2+160,372],fill=gold,width=3)
        d.polygon([(S/2,360),(S/2+13,372),(S/2,384),(S/2-13,372)],outline=gold,width=3)
    ctext(d,S/2,440,"Now Flying to Natchez",F(PAL_B,60),burg)
    url_pill(d,S/2,560,url,burg,(238,214,150))
    cf=fit(d,cta,PAL_BI,S-220,44); ctext(d,S/2,640,cta,cf,ink)
    ctext(d,S/2,740,"THE MOSE BEER HOUSE · DOWNTOWN NATCHEZ",F(PAL_R,24),gold,ls=2)
    ctext(d,S/2,792,"Daily United Express jet service · HEZ",F(PAL_I,28),ink)

# ---- 9 carriage ----
def carriage(img,url,cta):
    rose=(197,120,130); gold=(196,161,92); char=(58,42,44); cream=(250,243,238)
    img.paste(vgrad((S,S),(247,235,233),(230,206,208)).convert('RGB'),(0,0)); d=ImageDraw.Draw(img)
    d.rectangle([54,150,S-54,930],outline=gold,width=2)
    cx,cy,scl=S/2,300,15; pts=[]; t=math.pi
    while t>-math.pi:
        x=16*math.sin(t)**3; y=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t); pts.append((cx+x*scl,cy-y*scl)); t-=0.06
    for (pxx,pyy) in pts: d.ellipse([pxx-3.4,pyy-3.4,pxx+3.4,pyy+3.4],fill=(255,252,250),outline=(214,176,182))
    for s in (-1,1):
        bx=cx+s*330
        for k in range(6):
            yy=470+k*60; d.line([bx,yy,bx+s*30,yy-16],fill=gold,width=2); d.line([bx,yy,bx-s*4,yy+16],fill=gold,width=2)
    ctext(d,S/2,380,"A ROMANTIC ESCAPE FOR TWO",F(CEN_I,34),rose,ls=2)
    ctext(d,S/2,430,"Now Flying to Natchez",F(CEN_BI,64),char)
    url_pill(d,S/2,560,url,rose,cream)
    cf=fit(d,cta,CEN_BI,S-240,48); ctext(d,S/2,636,cta,cf,rose)
    ctext(d,S/2,740,"Daily United Express jets to HEZ · just the two of you",F(CEN_I,28),char)

VIBES={'synthwave':synthwave,'boarding_pass':boarding_pass,'departure':departure,'sky':sky,'jetsons':jetsons,'nagel':nagel,'ransom':ransom,'victorian':victorian,'carriage':carriage}
def base_for(v):
    return {'synthwave':vgrad((S,S),(18,8,40),(60,12,80)).convert('RGB'),
            'boarding_pass':vgrad((S,S),(214,234,248),(163,201,232)).convert('RGB'),
            'departure':Image.new('RGB',(S,S),(14,16,22)),
            'sky':vgrad((S,S),(94,170,232),(206,232,250)).convert('RGB'),
            'jetsons':Image.new('RGB',(S,S),(244,237,220)),
            'nagel':Image.new('RGB',(S,S),(46,150,148)),
            'ransom':Image.new('RGB',(S,S),(223,219,208)),
            'victorian':Image.new('RGB',(S,S),(243,233,212)),
            'carriage':Image.new('RGB',(S,S),(236,214,214))}.get(v,Image.new('RGB',(S,S),(255,255,255)))
def render(spec):
    v=spec.get('vibe','synthwave'); url=spec['url']; cta=spec.get('cta_sub','Come stay with us in Natchez!')
    if 'seed' in spec: random.seed(spec['seed'])
    img=base_for(v); VIBES.get(v,synthwave)(img,url,cta); return img
if __name__=='__main__':
    spec=json.load(open(sys.argv[1])); os.makedirs('flight-promo',exist_ok=True)
    out=os.path.join('flight-promo',spec['id']+'.png'); render(spec).save(out); print('wrote',out)
