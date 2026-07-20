#!/usr/bin/env python3
"""
Generate a branded Regalia B&B competitive-market card (1080x1080 PNG).

Reuses the visual system of tools/generate_review_card.py (wordmark, color schemes,
font pairings, frame + accent treatment). One card per PROPERTY, with one panel per
platform the property beats its comps on (Airbnb and/or VRBO), side by side when
both qualify. The SAVINGS is the hero. A "prices checked" stamp appears on-card, and
an optional book-direct line renders only when direct meaningfully wins.

Fonts needed (Debian/Ubuntu):
  sudo apt-get install -y fonts-urw-base35 fonts-lato fonts-crosextra-caladea fonts-liberation

Card spec (JSON via --data):
{
  "property": "Carriage House",
  "specs": "Entire cottage · 2 BR · 1 BA · Sleeps 4",
  "dates": "Fri Aug 21 – Sun Aug 23",
  "nights": 2,
  "checked": "Jul 20, 2026 · 10:20 AM CDT",
  "panels": [
    {"platform": "airbnb", "our_price": 316,
     "comps": [["Southern-Style Home", 388], ["Charming Cottage", 400]]},
    {"platform": "vrbo", "our_price": 343,
     "comps": [["Kelly Kottage", 476], ["Cozy Historic Cottage", 427]]}
  ],
  "direct_line": "BOOK DIRECT: $770 BEFORE TAX  ·  $34 LESS THAN AIRBNB",  # optional
  "cta": "LOWEST PRICE · BOOK ON AIRBNB"
}
"""
import argparse, json, random
from PIL import Image, ImageDraw, ImageFont

W = H = 1080
BRAND = "REGALIA B&B"

F = {
    "c059_rg": "/usr/share/fonts/opentype/urw-base35/C059-Roman.otf",
    "c059_bd": "/usr/share/fonts/opentype/urw-base35/C059-Bold.otf",
    "nimb_rg": "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Regular.otf",
    "nimb_bd": "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Bold.otf",
    "cal_rg":  "/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf",
    "cal_bd":  "/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf",
    "lato_rg": "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
    "lato_bd": "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
    "lato_bk": "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
}
THEMES = [
    {"head": "c059_bd", "num": "c059_bd", "label": "c059_rg", "htrack": 7},
    {"head": "lato_bk", "num": "lato_bk", "label": "lato_rg", "htrack": 9},
    {"head": "nimb_bd", "num": "nimb_bd", "label": "nimb_rg", "htrack": 6},
    {"head": "cal_bd",  "num": "cal_bd",  "label": "cal_rg",  "htrack": 6},
]
SCHEMES = [
    {"bg": (22, 48, 42),  "ink": (245, 239, 230), "acc": (201, 162, 39)},
    {"bg": (74, 31, 43),  "ink": (243, 231, 224), "acc": (217, 161, 91)},
    {"bg": (20, 35, 59),  "ink": (237, 239, 242), "acc": (198, 161, 91)},
    {"bg": (35, 35, 35),  "ink": (239, 237, 230), "acc": (167, 183, 155)},
    {"bg": (52, 36, 63),  "ink": (241, 233, 239), "acc": (201, 162, 39)},
    {"bg": (16, 50, 47),  "ink": (240, 234, 217), "acc": (224, 164, 88)},
    {"bg": (238, 230, 218), "ink": (58, 46, 39), "acc": (168, 74, 47), "light": True},
]
SCHEME_NAMES = ["forest", "wine", "navy", "charcoal", "plum", "teal", "cream"]
_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
PLATLABEL = {"airbnb": "Airbnb", "vrbo": "VRBO", "homeaway": "VRBO"}


def resolve_scheme(scheme):
    if scheme in (None, "") or isinstance(scheme, bool):
        return None
    if isinstance(scheme, int):
        return scheme % len(SCHEMES)
    s = str(scheme).strip().lower()
    if s.lstrip("-").isdigit():
        return int(s) % len(SCHEMES)
    return SCHEME_NAMES.index(s) if s in SCHEME_NAMES else None


def fnt(key, size):
    try:
        return ImageFont.truetype(F.get(key, key), size)
    except OSError:
        return ImageFont.truetype(_FALLBACK, size)


def tw(d, s, f, tr=0):
    return d.textlength(s, font=f) if tr == 0 else \
        sum(d.textlength(c, font=f) for c in s) + tr * max(0, len(s) - 1)


def draw_tracked(d, xy, s, f, fill, tr=0, anchor="l"):
    x, y = xy
    if anchor in ("m", "c"):
        x -= tw(d, s, f, tr) / 2
    for c in s:
        d.text((x, y), c, font=f, fill=fill)
        x += d.textlength(c, font=f) + tr


def rule(d, x1, x2, y, color, w=2):
    d.line([(x1, y), (x2, y)], fill=color, width=w)


def blend(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def money(v):
    return f"${int(round(v)):,}" if abs(v - round(v)) < 0.005 else f"${v:,.2f}"


def fit(d, s, key, maxw, start, mn, track=0):
    size = start
    while size > mn and tw(d, s, fnt(key, size), track) > maxw:
        size -= 2
    return size


def panel_savings(panel):
    our = panel["our_price"]
    prices = [p for _, p in panel["comps"]]
    return int(round(min(prices) - our)), int(round(max(prices) - our))


def draw_panel(d, cx, top, panel, th, s, show_sav=True):
    ink, acc, bg = s["ink"], s["acc"], s["bg"]
    plat = PLATLABEL.get(str(panel["platform"]).lower(), str(panel["platform"]))
    our = panel["our_price"]
    prices = [p for _, p in panel["comps"]]
    lo, hi = panel_savings(panel)
    n = len(panel["comps"])

    draw_tracked(d, (cx, top), plat.upper(), fnt(th["head"], 30), acc, 4, "c")
    draw_tracked(d, (cx, top + 44), "OUR TOTAL · BEFORE TAX",
                 fnt(th["label"], 16), blend(ink, bg, .22), 2, "c")
    hf = fnt(th["num"], 62)
    hs = money(our)
    d.text((cx - d.textlength(hs, font=hf) / 2, top + 66), hs, font=hf, fill=ink)
    draw_tracked(d, (cx, top + 150),
                 f"VS {n} HOME" + ("S" if n != 1 else "") + ":  " +
                 (money(min(prices)) if min(prices) == max(prices)
                  else f"{money(min(prices))}–{money(max(prices))}"),
                 fnt(th["label"], 22), blend(ink, bg, .12), 1, "c")
    if show_sav:
        sv = f"${lo} LESS" if lo == hi else f"${lo}–${hi} LESS"
        draw_tracked(d, (cx, top + 186), sv, fnt(th["head"], 24), acc, 1, "c")


def make_cma_card(data, out, seed=None, scheme=None):
    rng = random.Random(seed)
    idx = resolve_scheme(scheme)
    s = SCHEMES[idx] if idx is not None else rng.choice(SCHEMES)
    th = rng.choice(THEMES)
    ink, acc, bg = s["ink"], s["acc"], s["bg"]

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    cx = W // 2
    m = 62
    d.rectangle([m, m, W - m, H - m], outline=acc, width=2)
    d.rectangle([m + 9, m + 9, W - m - 9, H - m - 9], outline=blend(acc, bg, .35), width=1)

    # wordmark
    draw_tracked(d, (cx, 112), BRAND, fnt(th["head"], 42), ink, th["htrack"], "c")
    draw_tracked(d, (cx, 172), "NATCHEZ  ·  MISSISSIPPI", fnt(th["label"], 19), acc, 6, "c")
    rule(d, m + 70, W - m - 70, 214, blend(acc, bg, .25), 1)

    # property + specs
    pname = data["property"].upper()
    ps = fit(d, pname, th["head"], W - 2 * (m + 46), 54, 36, 3)
    draw_tracked(d, (cx, 240), pname, fnt(th["head"], ps), ink, 3, "c")
    draw_tracked(d, (cx, 240 + ps + 10), data["specs"].upper(),
                 fnt(th["label"], 20), blend(ink, bg, .18), 2, "c")

    # dates + checked stamp
    draw_tracked(d, (cx, 352), data["dates"].upper() + f"  ·  {data['nights']} NIGHTS",
                 fnt(th["label"], 21), acc, 2, "c")
    if data.get("checked"):
        cs = "PRICES CHECKED " + data["checked"].upper()
        csz = fit(d, cs, th["label"], W - 2 * (m + 40), 16, 12, 1)
        draw_tracked(d, (cx, 384), cs, fnt(th["label"], csz), blend(ink, bg, .35), 1, "c")

    # ---- HERO savings (the hook)
    panels = data["panels"]
    all_lo = min(panel_savings(p)[0] for p in panels)
    all_hi = max(panel_savings(p)[1] for p in panels)
    hero = f"SAVE ${all_lo}" if all_lo == all_hi else f"SAVE ${all_lo}–${all_hi}"
    hy = 430
    hfsz = fit(d, hero, th["num"], W - 2 * (m + 40), 118, 60, 0)
    d.text((cx - d.textlength(hero, font=fnt(th["num"], hfsz)) / 2, hy),
           hero, font=fnt(th["num"], hfsz), fill=acc)
    draw_tracked(d, (cx, hy + hfsz + 10), "VS COMPARABLE NATCHEZ HOMES",
                 fnt(th["label"], 22), ink, 4, "c")

    # ---- per-platform panels
    dl = data.get("direct_line")
    two = len(panels) == 2
    show_sav = two and not dl          # per-panel savings only add value on 2-up w/o direct
    ptop = 626 if two else 632
    if two:
        d.line([(cx, ptop + 4), (cx, ptop + 210)], fill=blend(acc, bg, .3), width=1)
        draw_panel(d, int(W * 0.28), ptop, panels[0], th, s, show_sav)
        draw_panel(d, int(W * 0.72), ptop, panels[1], th, s, show_sav)
    else:
        draw_panel(d, cx, ptop, panels[0], th, s, show_sav)

    # position direct line / footnote / cta
    if two and show_sav:
        foot_y, cta_y = 866, 936
    else:
        pb = ptop + 182
        y = pb + 12
        if dl:
            dsz = fit(d, dl, th["label"], W - 2 * (m + 26), 25, 15, 1)
            draw_tracked(d, (cx, y), dl, fnt(th["label"], dsz), ink, 1, "c")
            y += 46
        foot_y, cta_y = y, y + 56

    # comps footnote (credibility: name what we compared against)
    foot = []
    for p in panels:
        names = ", ".join(n for n, _ in p["comps"])
        foot.append(f"{PLATLABEL.get(str(p['platform']).lower(), p['platform'])}: {names}")
    fstr = "COMPARED VS  —  " + "   ·   ".join(foot)
    fsz = fit(d, fstr, th["label"], W - 2 * (m + 26), 18, 11, 1)
    draw_tracked(d, (cx, foot_y), fstr, fnt(th["label"], fsz), blend(ink, bg, .34), 1, "c")

    # CTA
    cta = data.get("cta", "")
    if cta:
        csz = fit(d, cta, th["head"], W - 2 * (m + 26), 30, 18, 2)
        draw_tracked(d, (cx, cta_y), cta, fnt(th["head"], csz), acc, 2, "c")

    img.convert("P", palette=Image.ADAPTIVE, colors=32).save(out, optimize=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--scheme", default=None)
    a = ap.parse_args()
    with open(a.data) as fh:
        data = json.load(fh)
    make_cma_card(data, a.out, seed=a.seed, scheme=a.scheme)
    print("wrote", a.out)
