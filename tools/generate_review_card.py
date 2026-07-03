#!/usr/bin/env python3
"""
Generate a branded Regalia B&B review card (1080x1080 PNG) from a 5-star review.

Variety is deterministic per --seed (pass the review id) so a given review always
renders the same card, but different reviews vary across color schemes, font
pairings, layouts, frames and star/divider treatments.

Usage:
  python3 generate_review_card.py --seed <review_id> \
      --name "Michael" \
      --quote "Great little carriage house loft in Natchez..." \
      --property "Carriage House · Natchez, MS" \
      --out /path/to/card.png
"""
import argparse, random, math, re
from PIL import Image, ImageDraw, ImageFont


def clean_name(n):
    """First name(s) only, joined by '&'. Never pass last names here — the task must
    supply guest.first_name (which may hold multiple first names like 'Mike And Debbie')."""
    n = (n or "").strip()
    n = re.sub(r"\s*(?:&|and|And|AND|\+)\s*", " & ", n)   # normalize joiners
    n = re.sub(r"\s+", " ", n).strip(" &")
    return n

W = H = 1080
BRAND = "REGALIA B&B"

# ---------------------------------------------------------------- fonts
F = {
    "c059_rg":  "/usr/share/fonts/opentype/urw-base35/C059-Roman.otf",
    "c059_bd":  "/usr/share/fonts/opentype/urw-base35/C059-Bold.otf",
    "c059_it":  "/usr/share/fonts/opentype/urw-base35/C059-Italic.otf",
    "nimb_rg":  "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Regular.otf",
    "nimb_bd":  "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Bold.otf",
    "nimb_it":  "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Italic.otf",
    "cal_rg":   "/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf",
    "cal_bd":   "/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf",
    "cal_it":   "/usr/share/fonts/truetype/crosextra/Caladea-Italic.ttf",
    "lora_it":  "/usr/share/fonts/truetype/google-fonts/Lora-Italic-Variable.ttf",
    "lato_rg":  "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
    "lato_lt":  "/usr/share/fonts/truetype/lato/Lato-Light.ttf",
    "lato_bd":  "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
    "lato_bk":  "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
    "libserif_it": "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
}

# font pairings: (heading, quote-italic, label)
THEMES = [
    {"head": "c059_bd", "quote": "c059_it",     "label": "c059_rg", "htrack": 7},
    {"head": "lato_bk", "quote": "libserif_it", "label": "lato_rg", "htrack": 9},
    {"head": "nimb_bd", "quote": "nimb_it",     "label": "nimb_rg", "htrack": 6},
    {"head": "cal_bd",  "quote": "cal_it",      "label": "cal_rg",  "htrack": 6},
    {"head": "lato_lt", "quote": "cal_it",      "label": "lato_rg", "htrack": 14},
    {"head": "c059_bd", "quote": "nimb_it",     "label": "lato_rg", "htrack": 8},
]

# color schemes: bg, ink (main text), accent, light? (dark text on light bg)
SCHEMES = [
    {"bg": (22, 48, 42),  "ink": (245, 239, 230), "acc": (201, 162, 39)},   # forest+gold
    {"bg": (74, 31, 43),  "ink": (243, 231, 224), "acc": (217, 161, 91)},   # wine+amber
    {"bg": (20, 35, 59),  "ink": (237, 239, 242), "acc": (198, 161, 91)},   # navy+brass
    {"bg": (35, 35, 35),  "ink": (239, 237, 230), "acc": (167, 183, 155)},  # charcoal+sage
    {"bg": (52, 36, 63),  "ink": (241, 233, 239), "acc": (201, 162, 39)},   # plum+gold
    {"bg": (16, 50, 47),  "ink": (240, 234, 217), "acc": (224, 164, 88)},   # teal+ochre
    {"bg": (238, 230, 218),"ink": (58, 46, 39),   "acc": (168, 74, 47), "light": True},  # cream+terracotta
]


_FALLBACK_RG = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
_FALLBACK_IT = "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"
_fcache = {}


def fnt(key, size, track=0):
    path = F.get(key, key)
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        fb = _FALLBACK_IT if key.endswith("_it") else _FALLBACK_RG
        return ImageFont.truetype(fb, size)


def tw(d, s, f, tr=0):
    if tr == 0:
        return d.textlength(s, font=f)
    return sum(d.textlength(c, font=f) for c in s) + tr * max(0, len(s) - 1)


def draw_tracked(d, xy, s, f, fill, tr=0, anchor="l"):
    x, y = xy
    if anchor in ("m", "c"):
        x -= tw(d, s, f, tr) / 2
    for c in s:
        d.text((x, y), c, font=f, fill=fill)
        x += d.textlength(c, font=f) + tr


def wrap(d, s, f, maxw):
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_quote(d, s, key, maxw, maxh, start=66, mn=32, lead=1.34):
    size = start
    while size >= mn:
        f = fnt(key, size)
        lines = wrap(d, s, f, maxw)
        lh = int(size * lead)
        if len(lines) * lh <= maxh and all(d.textlength(l, font=f) <= maxw for l in lines):
            return f, lines, lh
        size -= 2
    f = fnt(key, mn)
    return f, wrap(d, s, f, maxw), int(mn * lead)


def stars(d, cx, cy, acc, outer=30, gap=26, n=5):
    inner = outer * 0.42
    total = n * (2 * outer) + (n - 1) * gap
    sx = cx - total / 2 + outer
    for i in range(n):
        c = sx + i * (2 * outer + gap)
        pts = []
        for k in range(10):
            r = outer if k % 2 == 0 else inner
            a = -math.pi / 2 + k * math.pi / 5
            pts.append((c + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=acc)


def rule(d, x1, x2, y, color, w=2):
    d.line([(x1, y), (x2, y)], fill=color, width=w)


def corner_brackets(d, m, acc, ln=70, w=3):
    for (cx, cy, dx, dy) in [(m, m, 1, 1), (W - m, m, -1, 1),
                             (m, H - m, 1, -1), (W - m, H - m, -1, -1)]:
        d.line([(cx, cy), (cx + dx * ln, cy)], fill=acc, width=w)
        d.line([(cx, cy), (cx, cy + dy * ln)], fill=acc, width=w)


def blend(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_url(d, x, y, url, key, color, maxw, anchor="l", size=26, tr=1):
    """Draw a URL, shrinking to fit maxw so long https:// links never overflow."""
    while size >= 15:
        f = fnt(key, size)
        if tw(d, url, f, tr) <= maxw:
            break
        size -= 1
    draw_tracked(d, (x, y), url, fnt(key, size), color, tr, anchor)


# ---------------------------------------------------------------- layouts
def attrib(d, x, y, name, date, th, s, anchor="l"):
    """Draw '— Name' with a small dated line beneath it."""
    ink, acc, bg = s["ink"], s["acc"], s["bg"]
    draw_tracked(d, (x, y), f"— {name}", fnt(th["quote"], 44), acc, 1, anchor)
    if date:
        draw_tracked(d, (x, y + 58), date.upper(), fnt(th["label"], 19),
                     blend(ink, bg, .22), 5, anchor)


def layout_centered(d, img, s, th, rng, name, quote, prop, date, url):
    cx = W // 2
    bg, ink, acc = s["bg"], s["ink"], s["acc"]
    m = rng.choice([56, 62, 68])
    # frame variants
    fv = rng.choice(["double", "single", "rules"])
    if fv == "double":
        d.rectangle([m, m, W - m, H - m], outline=acc, width=2)
        d.rectangle([m + 9, m + 9, W - m - 9, H - m - 9], outline=blend(acc, bg, .35), width=1)
    elif fv == "single":
        d.rectangle([m, m, W - m, H - m], outline=acc, width=2)
    else:
        rule(d, m + 20, W - m - 20, 250, acc, 2)
        rule(d, m + 20, W - m - 20, 884, acc, 2)
    draw_tracked(d, (cx, 148), BRAND, fnt(th["head"], 46), ink, th["htrack"], "c")
    draw_tracked(d, (cx, 214), "NATCHEZ  ·  MISSISSIPPI", fnt(th["label"], 21), acc, 6, "c")
    stars(d, cx, 322, acc, outer=rng.choice([28, 32]), gap=rng.choice([24, 30]))
    qf, lines, lh = fit_quote(d, f'“{quote}”', th["quote"], W - 2 * (m + 60), 340)
    y = 410 + (340 - len(lines) * lh) // 2
    for ln in lines:
        d.text((cx - d.textlength(ln, font=qf) / 2, y), ln, font=qf, fill=ink)
        y += lh
    attrib(d, cx, 792, name, date, th, s, "c")
    draw_tracked(d, (cx, 902), prop.upper(), fnt(th["label"], 22), blend(ink, bg, .12), 4, "c")
    draw_url(d, cx, 946, url, th["head"], acc, W - 2 * (m + 34), "c", 26, 2)


def layout_editorial(d, img, s, th, rng, name, quote, prop, date, url):
    bg, ink, acc = s["bg"], s["ink"], s["acc"]
    m = 84
    corner_brackets(d, m, acc, ln=rng.choice([60, 80]), w=3)
    lx = m + 46
    draw_tracked(d, (lx, 128), BRAND, fnt(th["head"], 40), ink, th["htrack"])
    rule(d, lx, lx + 250, 190, acc, 2)
    # big opening quote mark
    bigq = fnt(th["quote"], 190)
    d.text((lx - 12, 210), "“", font=bigq, fill=blend(acc, bg, .18))
    qf, lines, lh = fit_quote(d, quote, th["quote"], W - lx - m - 30, 360, start=62)
    y = 360
    for ln in lines:
        d.text((lx, y), ln, font=qf, fill=ink)
        y += lh
    stars(d, lx + 120, y + 66, acc, outer=24, gap=20)
    attrib(d, lx, y + 110, name, date, th, s)
    draw_tracked(d, (lx, H - m - 92), prop.upper(), fnt(th["label"], 22), blend(ink, bg, .15), 4)
    draw_url(d, lx, H - m - 54, url, th["head"], acc, W - lx - m - 20, "l", 24, 1)


def layout_band(d, img, s, th, rng, name, quote, prop, date, url):
    cx = W // 2
    bg, ink, acc = s["bg"], s["ink"], s["acc"]
    band_h = rng.choice([196, 220])
    band_bottom = rng.choice([True, False])
    # top band in accent, reversed wordmark
    d.rectangle([0, 0, W, band_h], fill=acc)
    tcol = bg if not s.get("light") else (250, 246, 240)
    draw_tracked(d, (cx, band_h // 2 - 32), BRAND, fnt(th["head"], 44), tcol, th["htrack"], "c")
    draw_tracked(d, (cx, band_h // 2 + 26), "NATCHEZ  ·  MISSISSIPPI",
                 fnt(th["label"], 20), blend(tcol, acc, .25), 6, "c")
    stars(d, cx, band_h + 90, acc, outer=28, gap=26)
    qf, lines, lh = fit_quote(d, f'“{quote}”', th["quote"], W - 200, 320)
    y = band_h + 170 + (320 - len(lines) * lh) // 2
    for ln in lines:
        d.text((cx - d.textlength(ln, font=qf) / 2, y), ln, font=qf, fill=ink)
        y += lh
    attrib(d, cx, band_h + 500, name, date, th, s, "c")
    if band_bottom:
        d.rectangle([0, H - 84, W, H], fill=acc)
        draw_url(d, cx, H - 60, url, th["head"], tcol, W - 140, "c", 26, 2)
    else:
        draw_tracked(d, (cx, H - 150), prop.upper(), fnt(th["label"], 22),
                     blend(ink, bg, .15), 4, "c")
        draw_url(d, cx, H - 104, url, th["head"], acc, W - 160, "c", 26, 2)


def layout_bigquote(d, img, s, th, rng, name, quote, prop, date, url):
    cx = W // 2
    bg, ink, acc = s["bg"], s["ink"], s["acc"]
    draw_tracked(d, (cx, 110), BRAND, fnt(th["head"], 40), ink, th["htrack"], "c")
    rule(d, cx - 60, cx + 60, 162, acc, 2)
    bigf = fnt(th["quote"], 200)
    d.text((cx - d.textlength("“", font=bigf) / 2, 202), "“", font=bigf, fill=blend(acc, bg, .22))
    qf, lines, lh = fit_quote(d, quote, th["quote"], W - 220, 360, start=70)
    y = 430 + (360 - len(lines) * lh) // 2
    for ln in lines:
        d.text((cx - d.textlength(ln, font=qf) / 2, y), ln, font=qf, fill=ink)
        y += lh
    stars(d, cx, 828, acc, outer=24, gap=22)
    attrib(d, cx, 872, name, date, th, s, "c")
    draw_tracked(d, (cx, 960), prop.upper(), fnt(th["label"], 20), blend(ink, bg, .12), 4, "c")
    draw_url(d, cx, 996, url, th["head"], acc, W - 160, "c", 24, 2)


LAYOUTS = [layout_centered, layout_editorial, layout_band, layout_bigquote]


def make_card(name, quote, prop, out, seed=None, date="", url="https://regaliabnb.com", colors=24):
    name = clean_name(name)
    rng = random.Random(seed)
    s = rng.choice(SCHEMES)
    th = rng.choice(THEMES)
    layout = rng.choice(LAYOUTS)
    img = Image.new("RGB", (W, H), s["bg"])
    d = ImageDraw.Draw(img)
    layout(d, img, s, th, rng, name, quote, prop, date, url)
    # palette-optimize (flat art) to keep PNG + base64 small
    img.convert("P", palette=Image.ADAPTIVE, colors=colors).save(out, optimize=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--quote", required=True)
    ap.add_argument("--property", dest="prop", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--date", default="")
    ap.add_argument("--url", default="regaliabnb.com")
    a = ap.parse_args()
    make_card(a.name, a.quote, a.prop, a.out, seed=a.seed, date=a.date, url=a.url)
    print("wrote", a.out)
