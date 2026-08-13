#!/usr/bin/env python3
"""Regalia Booking.com photo collage renderer.

Reads a queue spec JSON and composites 3 remote listing photos into a single
1080x1080 social image with a crop-safe center ribbon.

Standard spec:
  {
    "id": "booking-<slug>-<stamp>",
    "kind": "photo_collage",
    "photos": ["<url>", "<url>", "<url>"],
    "title": "The Mose Beer House",
    "tagline": "Downtown Natchez, MS Grand Victorian",
    "subtitle": "NOW ON BOOKING.COM",
    "theme": "victorian" | "carriage"
  }

Promo variant — add "headline" (and optionally "fineprint") to get a taller
ribbon led by the offer:
  {
    ...,
    "headline": "20% OFF",
    "title": "The Mose Beer House - Natchez, MS",
    "subtitle": "NEW LISTING PROMO ON BOOKING.COM",
    "fineprint": "Limited time only - First 3 Booking.com bookings eligible"
  }

Usage: python3 tools/render_booking_collage.py <queue.json>
   ->  booking-collage/<id>.png
"""
import sys, os, json, glob, io, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps

S = 1080
GUTTER = 6
HERO_H = 445          # top hero band (standard ribbon)
RIBBON_H = 190        # crop-safe center ribbon (standard)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

THEMES = {
    "victorian": {"paper": (247, 239, 221), "ink": (43, 32, 22),
                  "accent": (110, 34, 51), "rule": (176, 135, 59)},
    "carriage":  {"paper": (250, 243, 238), "ink": (58, 42, 44),
                  "accent": (168, 74, 90), "rule": (196, 161, 92)},
}


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
LATO_BOLD = find_font('Lato-Bold.ttf')


def F(path, size):
    return ImageFont.truetype(path, size)


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = r.read()
    im = Image.open(io.BytesIO(data))
    return im.convert('RGB')


def ctext(d, cx, y, text, font, fill, ls=0):
    if ls:
        widths = [d.textlength(c, font=font) for c in text]
        total = sum(widths) + ls * (len(text) - 1)
        x = cx - total / 2
        for c, w in zip(text, widths):
            d.text((x, y), c, font=font, fill=fill)
            x += w + ls
        return
    d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill)


def fit_font(d, text, path, maxw, start, floor=16, ls=0):
    size = start
    while size > floor:
        f = F(path, size)
        w = sum(d.textlength(c, font=f) for c in text) + ls * (len(text) - 1)
        if w <= maxw:
            return f
        size -= 1
    return F(path, floor)


def collage(spec):
    theme = THEMES.get(spec.get('theme', 'victorian'), THEMES['victorian'])
    photos = spec['photos']
    if len(photos) < 3:
        raise SystemExit('need 3 photos, got %d' % len(photos))

    promo = bool(spec.get('headline'))
    ribbon_h = 255 if promo else RIBBON_H
    hero_h = (S - ribbon_h) // 2 + (35 if promo else 0)

    img = Image.new('RGB', (S, S), theme['paper'])

    # --- top hero, full width ---
    hero = ImageOps.fit(fetch(photos[0]), (S, hero_h), method=Image.LANCZOS,
                        centering=(0.5, 0.5))
    img.paste(hero, (0, 0))

    # --- bottom pair ---
    bot_y = hero_h + ribbon_h
    bot_h = S - bot_y
    half_w = (S - GUTTER) // 2
    for i, url in enumerate(photos[1:3]):
        tile = ImageOps.fit(fetch(url), (half_w, bot_h), method=Image.LANCZOS,
                            centering=(0.5, 0.5))
        img.paste(tile, (i * (half_w + GUTTER), bot_y))

    # --- crop-safe center ribbon ---
    d = ImageDraw.Draw(img)
    d.rectangle([0, hero_h, S, bot_y], fill=theme['paper'])
    d.line([0, hero_h + 3, S, hero_h + 3], fill=theme['rule'], width=3)
    d.line([0, bot_y - 3, S, bot_y - 3], fill=theme['rule'], width=3)

    title = spec.get('title', '')
    tagline = spec.get('tagline', '')          # e.g. "Natchez, MS"
    subtitle = spec.get('subtitle', 'NOW ON BOOKING.COM')

    if promo:
        headline = spec['headline']            # e.g. "20% OFF"
        fineprint = spec.get('fineprint', '')

        hf = fit_font(d, headline, LATO_BLACK, S - 120, 96)
        ctext(d, S / 2, hero_h + 8, headline, hf, theme['accent'])

        tf = fit_font(d, title, LATO_BLACK, S - 140, 40)
        ctext(d, S / 2, hero_h + 116, title, tf, theme['ink'])

        sf = fit_font(d, subtitle, LATO_BOLD, S - 180, 24, ls=5)
        ctext(d, S / 2, hero_h + 168, subtitle, sf, theme['ink'], ls=5)

        if fineprint:
            ff = fit_font(d, fineprint, LATO_BOLD, S - 90, 19)
            ctext(d, S / 2, hero_h + 212, fineprint, ff, (128, 122, 112))
        return img

    tf = fit_font(d, title, LATO_BLACK, S - 140, 58)
    ctext(d, S / 2, hero_h + 16, title, tf, theme['ink'])

    gf = fit_font(d, tagline, LATO_BOLD, S - 120, 32)
    ctext(d, S / 2, hero_h + 84, tagline, gf, theme['ink'])

    sf = fit_font(d, subtitle, LATO_BOLD, S - 200, 27, ls=6)
    ctext(d, S / 2, hero_h + 136, subtitle, sf, theme['accent'], ls=6)

    return img


if __name__ == '__main__':
    spec = json.load(open(sys.argv[1]))
    outdir = 'booking-collage'
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, spec['id'] + '.png')
    collage(spec).save(out, optimize=True)
    print('wrote', out, os.path.getsize(out), 'bytes')
