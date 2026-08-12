#!/usr/bin/env python3
"""Render a queued card from a JSON descriptor (run in CI by the workflow).

Handles three kinds of queue entries, all under review-cards/queue/*.json:

1. Review card (original): keys id, name, quote, property, date, url; seed
   defaults to id; optional scheme. Output: review-cards/<id>.png

2. CMA card: identified by the presence of a "panels" key. The JSON is the
   generate_cma_card.py spec (property, specs, dates, nights, checked, panels,
   optional direct_line, cta) plus control keys out (target PNG path, defaults
   to review-cards/<stem>.png), seed (defaults to stem) and optional scheme.

3. Photo collage: identified by "kind": "photo_collage". The JSON is the
   render_booking_collage.py spec (id, photos, title, subtitle, theme).
   Output: review-cards/<id>.png

Usage: python3 tools/render_from_queue.py review-cards/queue/<name>.json
"""
import sys, json, os, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(modfile, name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(HERE, modfile))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


path = sys.argv[1]
data = json.load(open(path))
stem = os.path.splitext(os.path.basename(path))[0]

# --- Photo collage branch (identified by kind == "photo_collage") ---
if data.get("kind") == "photo_collage":
    bc = _load("render_booking_collage.py", "bc")
    out = data.get("out") or os.path.join(
        "review-cards", "%s.png" % data.get("id", stem))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bc.collage(data).save(out, optimize=True)
    print("rendered", out, os.path.getsize(out), "bytes")
    sys.exit(0)

# --- CMA card branch (identified by "panels") ---
if "panels" in data:
    gc = _load("generate_cma_card.py", "gc")
    out = data.get("out") or os.path.join("review-cards", f"{stem}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    gc.make_cma_card(data, out, seed=data.get("seed", stem),
                     scheme=data.get("scheme"))
    print("rendered", out)
    sys.exit(0)

# --- Review card branch (original behavior) ---
g = _load("generate_review_card.py", "g")
rid = data["id"]
out = os.path.join("review-cards", f"{rid}.png")

# The verified badge derives from the cardId prefix (no separate field needed):
#   airb- -> airbnb, vrbo- -> vrbo, hosp- -> hospitable
PREFIX_PLATFORM = {"airb": "airbnb", "vrbo": "vrbo", "hosp": "hospitable"}
platform = PREFIX_PLATFORM.get(rid.split("-", 1)[0], "")

g.make_card(
    data["name"], data["quote"], data["property"], out,
    seed=data.get("seed", rid),
    date=data.get("date", ""),
    url=data.get("url", "https://regaliabnb.com"),
    platform=platform,
    scheme=data.get("scheme"),
)
print("rendered", out)
